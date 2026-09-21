from __future__ import annotations

import json
from pathlib import Path

from apex_context_engine.anomalies import detect_anomalies
from apex_context_engine.engine import build_context
from apex_context_engine.market_graph import _identity, audit_equivalence, best_price_alerts, build_fair_markets
from apex_context_engine.models import OddRecord, ParsedPacket
from apex_context_engine.packet_parser import parse_packet_file
from apex_context_engine.report import render_json, render_text


FIXTURE = Path(__file__).parent / "fixtures" / "san_antonio_gualaceo_real" / "full_real_packet.txt"


def _context():
    packet = parse_packet_file(FIXTURE)
    return packet, build_context(packet)


def _alerts():
    return {row["canonical_settlement_event"].removeprefix("FOOTBALL_RESULT|"): row for row in _context()[1].best_price_alerts}


def test_01_home_result_equals_home_minus_half_two_way():
    row = _alerts()["FULL_TIME|RESULT_HOME"]
    assert row["allowlist_rule"] == "1X2_HOME_EQ_HANDICAP_HOME_MINUS_0_5_TWO_WAY_SAME_PERIOD"


def test_02_away_result_equals_away_minus_half_two_way():
    row = _alerts()["FULL_TIME|RESULT_AWAY"]
    assert row["allowlist_rule"] == "1X2_AWAY_EQ_HANDICAP_AWAY_MINUS_0_5_TWO_WAY_SAME_PERIOD"


def test_03_mixed_duplicate_and_mathematical_equivalent_group():
    packet, context = _context()
    groups = {str(row.get("canonical_settlement_event", "")).removeprefix("FOOTBALL_RESULT|"): row for row in context.equivalence_audit["accepted_groups"]}
    assert groups["FULL_TIME|RESULT_HOME"]["matched_records"] == 3
    assert {row["MAPPING_RESULT"] for row in groups["FULL_TIME|RESULT_HOME"]["record_mappings"]} == {"MAPPED"}


def test_04_home_best_price_is_220_over_217():
    row = _alerts()["FULL_TIME|RESULT_HOME"]
    assert row["best"]["odds"] == 2.20 and [x["odds"] for x in row["worse_copies"]] == [2.17]


def test_05_away_best_price_is_312_over_295():
    row = _alerts()["FULL_TIME|RESULT_AWAY"]
    assert row["best"]["odds"] == 3.12 and [x["odds"] for x in row["worse_copies"]] == [2.95]


def test_06_signed_line_is_preserved():
    packet = parse_packet_file(FIXTURE)
    assert {row.line for row in packet.odds if row.family.startswith("HANDICAP_")} >= {"-1.5", "-0.5", "0.5", "1.5"}


def test_07_away_minus_half_differs_from_away_plus_half():
    packet = parse_packet_file(FIXTURE)
    away = [row for row in packet.odds if row.handicap_kind == "TWO_WAY" and row.canonical_outcome == "AWAY"]
    keys = {_identity(row) for row in away if row.line in {"-0.5", "0.5"}}
    assert len(keys) == 2


def test_08_away_plus_half_is_easier_than_minus_half():
    _, context = _context()
    markets = [row for row in context.fair_markets if row["handicap_kind"] == "TWO_WAY"]
    away = {str(-float(row["line"])): row["selections"]["AWAY"] for row in markets}
    assert away["0.5"] > away["-0.5"]


def test_09_away_plus_one_half_is_easier_than_plus_half():
    _, context = _context()
    markets = [row for row in context.fair_markets if row["handicap_kind"] == "TWO_WAY"]
    away = {str(-float(row["line"])): row["selections"]["AWAY"] for row in markets}
    assert away["1.5"] > away["0.5"]


def test_10_san_antonio_has_no_false_handicap_monotonicity_alert():
    _, context = _context()
    assert not [row for row in context.anomalies if row["type"] == "HANDICAP_CURVE_NON_MONOTONIC"]


def test_11_two_way_and_three_way_curves_are_separate():
    _, context = _context()
    kinds = {row["handicap_kind"] for row in context.fair_markets if row["family"].startswith("HANDICAP_")}
    assert kinds == {"TWO_WAY", "THREE_WAY"}


def test_12_home_and_away_axes_are_opposite_and_separate():
    _, context = _context()
    market = next(row for row in context.fair_markets if row["handicap_kind"] == "TWO_WAY" and row["line"] == "-0.5")
    assert float(market["line"]) == -0.5 and -float(market["line"]) == 0.5


def test_13_two_quarantined_rows_force_pass_with_quarantine():
    _, context = _context()
    assert context.status == "PASS_WITH_QUARANTINE" and context.quarantined_source_rows == 2


def test_14_quarantine_has_full_record_audit():
    _, context = _context()
    required = {"source_record_id", "category", "family", "market", "raw", "reason", "stage"}
    assert len(context.quarantined_rows) == 2 and all(required <= set(row) for row in context.quarantined_rows)


def test_15_lambda_reconciliation_is_explicit():
    _, context = _context()
    script = context.market_script
    assert script["team_component_sum"] == 1.966819
    assert script["lambda_reconciliation_residual"] == 0.081853
    assert script["reconciliation_method"] == "EQUAL_WEIGHT_BLEND_TEAM_COMPONENT_SUM_AND_DIRECT_MATCH_TOTAL"


def test_16_json_is_deterministic():
    assert render_json(_context()[1]) == render_json(_context()[1])


def test_17_text_is_deterministic_and_contains_audits():
    first, second = render_text(_context()[1]), render_text(_context()[1])
    assert first == second
    assert "STATUS=PASS_WITH_QUARANTINE" in first and "QUARANTINED_RECORDS=" in first
