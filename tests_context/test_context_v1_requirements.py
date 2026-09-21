import json
import subprocess
from pathlib import Path

import pytest

from apex_context_engine.devig import DevigError, devig, power, shin
from apex_context_engine.engine import build_context
from apex_context_engine.gui_adapter_contract import packet_is_ready, run_context_engine
from apex_context_engine.market_graph import best_price_alerts, canonical_signature
from apex_context_engine.models import OddRecord
from apex_context_engine.packet_parser import PacketParseError, parse_packet_text
from apex_context_engine.poisson import invert_over_probability, probability_total_over, top_scores
from apex_context_engine.report import render_json, render_text

FIXTURE = Path(__file__).parent / "fixtures" / "minimal_packet.txt"


def fixture_text() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def odd(**changes) -> OddRecord:
    values = dict(category="Top", family="GOALS_OU", market="Total", period="FULL_TIME", owner="", selection="OVER", line="2.5", handicap_kind="", handicap_taxonomy="", settlement="NO_PUSH", odds=2.0, raw="Powyżej 2,5", source_index=1)
    values.update(changes)
    return OddRecord(**values)


def append_odd(text: str, **fields) -> str:
    defaults = dict(CATEGORY="Test", FAMILY="DNB", MARKET="Draw no bet", PERIOD="FULL_TIME", OWNER="Home FC", SELECTION="HOME", LINE="", HANDICAP_KIND="TWO_WAY", HANDICAP_TAXONOMY="DNB", SETTLEMENT="PUSH_ON_DRAW", ODDS="1.50", RAW="Home DNB")
    defaults.update(fields)
    body = "\n".join(f'{key}="{value}";' for key, value in defaults.items())
    return text + f"\nODD{{\n{body}\n}}\n"


def test_missing_header_fails_closed():
    with pytest.raises(PacketParseError):
        parse_packet_text("ODD{}")


@pytest.mark.parametrize("replacement, reason", [
    ('ODDS="0";', "ODD_NOT_ABOVE_ONE"),
    ('ODDS="abc";', "ODD_INVALID_NUMBER"),
])
def test_bad_odds_block_context(replacement, reason):
    text = fixture_text().replace('ODDS="1.80";', replacement, 1)
    context = build_context(parse_packet_text(text))
    assert context.status == "BLOCKED"
    normalized_reason = "ODDS_NOT_ABOVE_ONE" if reason == "ODD_NOT_ABOVE_ONE" else "INVALID_NUMBER"
    assert any(any(normalized_reason in row_reason for row_reason in row["reasons"]) for row in context.quarantined_rows)


def test_decimal_comma_and_utf8_bom_are_preserved():
    text = "\ufeff" + fixture_text().replace('ODDS="1.80";', 'ODDS="1,80";', 1).replace("Home FC", "ŁKS Łódź")
    packet = parse_packet_text(text)
    assert packet.odds[0].odds == 1.8
    assert packet.header["MATCH"].startswith("ŁKS Łódź")


def test_similar_team_names_and_team_total_owners_are_not_collapsed():
    text = fixture_text().replace("Home FC - Away FC", "United - United City").replace("Home FC", "United").replace("Away FC", "United City")
    packet = parse_packet_text(text)
    owners = {row.owner for row in packet.odds if row.family.startswith("TEAM_TOTALS_")}
    assert owners == {"United", "United City"}


@pytest.mark.parametrize("period", ["FULL_TIME", "1ST_HALF", "2ND_HALF"])
def test_periods_parse(period):
    packet = parse_packet_text(fixture_text().replace('PERIOD="FULL_TIME";', f'PERIOD="{period}";'))
    assert {row.period for row in packet.odds} == {period}


@pytest.mark.parametrize("family,kind,line,selection,settlement", [
    ("DNB", "TWO_WAY", "", "HOME", "PUSH_ON_DRAW"),
    ("DOUBLE_CHANCE", "THREE_WAY", "", "HOME_OR_DRAW", "WIN_LOSE"),
    ("HANDICAP_EUROPEAN", "TWO_WAY", "-0.5", "HOME", "NO_PUSH"),
    ("HANDICAP_EUROPEAN", "THREE_WAY", "+1.0", "AWAY", "PUSH_POSSIBLE"),
])
def test_market_taxonomy_fields_are_preserved(family, kind, line, selection, settlement):
    text = append_odd(fixture_text(), FAMILY=family, HANDICAP_KIND=kind, LINE=line, SELECTION=selection, SETTLEMENT=settlement)
    text = text.replace("ODDS_COUNT=9;", "ODDS_COUNT=10;")
    row = parse_packet_text(text).odds[-1]
    expected_line = f"{float(line):g}" if line else ""
    assert (row.family, row.handicap_kind, row.line, row.selection, row.settlement) == (family, kind, expected_line, selection, settlement)


def test_shin_power_and_explicit_fallback():
    p3, z = shin([1.8, 3.5, 4.5])
    p2 = power([1.8, 2.05])
    fallback, method, detail, warnings = devig([1.8, 2.05], "SHIN")
    assert abs(sum(p3) - 1) < 1e-9 and abs(sum(p2) - 1) < 1e-9
    assert 0 <= z < 1
    assert method == "MULTIPLICATIVE_FALLBACK" and detail["preferred"] == "SHIN" and warnings
    assert abs(sum(fallback) - 1) < 1e-9


def test_poisson_inversion_and_central_scores():
    lam = invert_over_probability(2.5, 0.55)
    assert probability_total_over(2.5, lam) == pytest.approx(0.55, abs=1e-9)
    scores = top_scores(1.5, 1.0)
    assert len(scores) == 6 and all(":" in row["score"] for row in scores)


def test_lambda_offense_map_line_discipline_and_no_recommendations():
    context = build_context(parse_packet_text(fixture_text()))
    assert context.market_script["lambda_home"] is not None
    assert context.market_script["lambda_away"] is not None
    assert "MATCH_OVER_2_5" in context.offense_map["metrics"]
    scores = {row["score"] for row in context.line_discipline["natural_score_scenarios"]}
    assert {"1:0", "2:0", "2:1", "1:1"} <= scores
    report = render_text(context)
    assert "RECOMMEND" not in report.upper() and "PLAY / NO BET" not in report.upper()


def test_equivalence_signature_separates_period_owner_line_and_settlement():
    base = odd()
    signatures = {
        canonical_signature(base), canonical_signature(odd(period="1ST_HALF")), canonical_signature(odd(owner="Home")),
        canonical_signature(odd(line="3.5")), canonical_signature(odd(settlement="PUSH_POSSIBLE")),
    }
    assert len(signatures) == 5


def test_best_price_only_for_exact_semantics():
    records = [odd(market="Total", category="A", odds=2.0), odd(market="Total", category="B", odds=2.2), odd(market="Total", category="C", odds=3.0, settlement="PUSH_POSSIBLE")]
    alerts = best_price_alerts(records)
    assert len(alerts) == 1
    assert alerts[0]["best"]["odds"] == 2.2
    assert alerts[0]["safety"] == "PASS_EXACT_SEMANTIC_IDENTITY"


def test_fail_closed_truth_and_count_mismatch():
    text = fixture_text().replace('ANALYSIS_READY="YES";', 'ANALYSIS_READY="NO";').replace("ODDS_COUNT=9;", "ODDS_COUNT=99;")
    context = build_context(parse_packet_text(text))
    assert context.status == "BLOCKED"
    assert any("ODDS_COUNT_MISMATCH" in row for row in context.blocked_reasons)


def test_byte_deterministic_json_and_txt_three_runs():
    packet = parse_packet_text(fixture_text())
    outputs = [(render_json(build_context(packet)), render_text(build_context(packet))) for _ in range(3)]
    assert outputs[0] == outputs[1] == outputs[2]


def test_packet_readiness_contract():
    assert packet_is_ready(fixture_text())
    assert not packet_is_ready("")
    assert not packet_is_ready('BETCLIC_FULL_ODDS_PACKET{\nMATCH="Home - Away";\nCOMPETITION="X";\n}\nODD{\n}')
    assert not packet_is_ready(fixture_text().replace("ODDS_COUNT=9;", "ODDS_COUNT=99;"))


def test_adapter_missing_module_isolated(tmp_path):
    result = run_context_engine(fixture_text(), tmp_path / "missing", tmp_path / "out")
    assert result.status == "BLOCKED" and result.reason == "CONTEXT_ENGINE_MODULE_NOT_FOUND"


def test_adapter_timeout_isolated(tmp_path, monkeypatch):
    module = tmp_path / "module" / "apex_context_engine"
    module.mkdir(parents=True)
    (module / "cli.py").write_text("", encoding="utf-8")
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("cmd", 0.01)
    monkeypatch.setattr(subprocess, "run", timeout)
    result = run_context_engine(fixture_text(), module.parent, tmp_path / "out", 0.01)
    assert result.status == "BLOCKED" and result.reason == "CONTEXT_ENGINE_TIMEOUT"


def test_adapter_unexpected_subprocess_error_isolated(tmp_path, monkeypatch):
    module = tmp_path / "module" / "apex_context_engine"
    module.mkdir(parents=True)
    (module / "cli.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    result = run_context_engine(fixture_text(), module.parent, tmp_path / "out")
    assert result.status == "BLOCKED"
    assert result.reason == "CONTEXT_ENGINE_ERROR:RuntimeError:boom"


def test_adapter_missing_declared_outputs_is_blocked(tmp_path, monkeypatch):
    module = tmp_path / "module" / "apex_context_engine"
    module.mkdir(parents=True)
    (module / "cli.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs: subprocess.CompletedProcess(
        command, 0, "CONTEXT_ENGINE_STATUS=PASS\nJSON=missing.json\nTEXT=missing.txt\n", ""))
    result = run_context_engine(fixture_text(), module.parent, tmp_path / "out")
    assert result.status == "BLOCKED"
    assert result.reason == "CONTEXT_ENGINE_OUTPUT_MISSING:JSON,TEXT"


def test_unicode_json_roundtrip():
    context = build_context(parse_packet_text(fixture_text().replace("Test League", "I liga – Łódź")))
    encoded = render_json(context)
    assert "Łódź" in encoded
    assert json.loads(encoded)["input_truth"]["COMPETITION"] == "I liga – Łódź"
