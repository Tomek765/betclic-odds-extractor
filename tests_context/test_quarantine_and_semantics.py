from __future__ import annotations

from pathlib import Path

from apex_context_engine.engine import build_context
from apex_context_engine.packet_parser import parse_packet_text
from apex_context_engine.semantic_resolver import SEMANTIC_RULE_IDS, resolve_semantics


FIXTURE = Path(__file__).parent / "fixtures" / "minimal_packet.txt"


def fixture() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def test_semantic_rule_ids_are_unique_and_closed():
    assert len(SEMANTIC_RULE_IDS) == len(set(SEMANTIC_RULE_IDS)) == 13


def test_explicit_settlement_is_preserved_without_rule():
    fields, audit, reasons = resolve_semantics({"FAMILY": "1X2", "MARKET": "Wynik", "SETTLEMENT": "WIN_LOSE"})
    assert fields["SETTLEMENT"] == "WIN_LOSE" and audit == [] and reasons == []


def test_total_half_line_resolution_is_exact():
    fields, audit, reasons = resolve_semantics({"FAMILY": "GOALS_OU", "MARKET": "Gole", "LINE": "2.5", "SETTLEMENT": ""})
    assert fields["SETTLEMENT"] == "NO_PUSH" and audit[0]["confidence"] == "EXACT" and not reasons


def test_total_integer_line_resolution_keeps_push():
    fields, _, reasons = resolve_semantics({"FAMILY": "GOALS_OU", "MARKET": "Gole", "LINE": "2", "SETTLEMENT": ""})
    assert fields["SETTLEMENT"] == "PUSH_POSSIBLE" and not reasons


def test_unknown_family_is_quarantined_not_guessed():
    text = fixture().replace('FAMILY="1X2";', 'FAMILY="MYSTERY";', 1).replace('SETTLEMENT="WIN_LOSE";', 'SETTLEMENT="";', 1)
    context = build_context(parse_packet_text(text))
    assert context.status == "BLOCKED"
    assert any("SETTLEMENT_SEMANTICS_UNPROVEN" in row["reasons"] for row in context.quarantined_rows)


def test_single_bad_optional_row_does_not_block_safe_core():
    extra = fixture().replace("ODDS_COUNT=9;", "ODDS_COUNT=10;").replace("\nODD{", "\nODD{", 1)
    bad = '''\nODD{\nCATEGORY="Optional";\nFAMILY="MYSTERY";\nMARKET="Unknown";\nPERIOD="FULL_TIME";\nOWNER="";\nSELECTION="X";\nLINE="";\nSETTLEMENT="";\nODDS="2.0";\n}\n'''
    context = build_context(parse_packet_text(extra + bad))
    assert context.status == "PASS_WITH_QUARANTINE" and len(context.quarantined_rows) == 1


def test_no_full_time_1x2_is_packet_level_block():
    text = fixture().replace('FAMILY="1X2";', 'FAMILY="MYSTERY";').replace('SETTLEMENT="WIN_LOSE";', 'SETTLEMENT="";')
    context = build_context(parse_packet_text(text))
    assert context.status == "BLOCKED"
    assert "MINIMAL_CORE_MISSING_FULL_TIME_1X2" in context.blocked_reasons


def test_quarantine_contract_is_present_in_json_model():
    context = build_context(parse_packet_text(fixture()))
    payload = context.to_dict()
    for key in ("accepted_rows", "quarantined_rows", "quarantine_reasons", "core_coverage", "optional_coverage", "unsupported_families", "semantic_resolutions"):
        assert key in payload


def test_semantic_resolution_does_not_depend_on_odds():
    a, audit_a, _ = resolve_semantics({"FAMILY": "BTTS", "MARKET": "BTTS", "ODDS": "1.01", "SETTLEMENT": ""})
    b, audit_b, _ = resolve_semantics({"FAMILY": "BTTS", "MARKET": "BTTS", "ODDS": "99", "SETTLEMENT": ""})
    assert a["SETTLEMENT"] == b["SETTLEMENT"] == "WIN_LOSE"
    assert audit_a[0]["rule_id"] == audit_b[0]["rule_id"]


def test_resolver_is_deterministic():
    fields = {"FAMILY": "DNB", "MARKET": "Remis - zwrot", "PERIOD": "FULL_TIME", "SELECTION": "HOME", "LINE": "", "SETTLEMENT": ""}
    assert resolve_semantics(fields) == resolve_semantics(fields) == resolve_semantics(fields)
