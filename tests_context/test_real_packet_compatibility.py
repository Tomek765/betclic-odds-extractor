from __future__ import annotations

from pathlib import Path

import json
import jsonschema

from apex_context_engine.engine import build_context
from apex_context_engine.packet_parser import parse_packet_text
from apex_context_engine.report import render_json


FIXTURE = Path(__file__).parent / "fixtures" / "minimal_packet.txt"


def packet_text() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def status(text: str):
    return build_context(parse_packet_text(text))


def test_current_contract_passes():
    assert status(packet_text()).status == "PASS"


def test_older_contract_with_analysis_ready_equivalent_passes():
    text = packet_text().replace('CLEAN_CORE_READY="YES";\n', "").replace('FULL_USABLE_READY="YES";\n', "")
    assert status(text).status == "PASS"


def test_partial_parser_with_explicit_clean_core_passes():
    text = packet_text().replace('PARSER_TRUTH_STATUS="PASS";', 'PARSER_TRUTH_STATUS="PARTIAL";').replace('ANALYSIS_READY="YES";', 'ANALYSIS_READY="NO";')
    assert status(text).status == "PASS"


def test_non_exhaustive_full_usable_packet_passes():
    text = packet_text().replace('CLEAN_CORE_READY="YES";', 'CLEAN_CORE_READY="NO";').replace('ANALYSIS_READY="YES";', 'ANALYSIS_READY="NO";')
    text = text.replace('FULL_USABLE_READY="YES";', 'FULL_USABLE_READY="YES";\nEXHAUSTIVE_READY="NO";')
    assert status(text).status == "PASS"


def test_quarantined_unresolved_does_not_block_clean_core():
    text = packet_text().replace('UNRESOLVED_COUNT="0";', 'UNRESOLVED_COUNT="7";')
    context = status(text)
    assert context.status == "PASS"
    assert "INPUT_HAS_ROW_LEVEL_UNRESOLVED:7" in context.warnings


def test_unresolved_without_clean_core_is_row_level_warning_when_core_reconstructs():
    text = packet_text().replace('CLEAN_CORE_READY="YES";', 'CLEAN_CORE_READY="NO";').replace('UNRESOLVED_COUNT="0";', 'UNRESOLVED_COUNT="7";')
    context = status(text)
    assert context.status == "PASS"
    assert "INPUT_HAS_ROW_LEVEL_UNRESOLVED:7" in context.warnings


def test_optional_header_fields_may_be_absent():
    text = packet_text()
    for line in ('KICKOFF="18:00";\n', 'MARKET_COUNT=4;\n', 'ODDS_COUNT=9;\n', 'COMPLETENESS_SCORE="100.0";\n'):
        text = text.replace(line, "")
    assert status(text).status == "PASS"


def test_optional_non_handicap_taxonomy_fields_may_be_absent():
    text = packet_text().replace('HANDICAP_KIND="";\n', "").replace('HANDICAP_TAXONOMY="";\n', "")
    assert status(text).status == "PASS"


def test_missing_exact_1x2_settlement_is_canonically_resolved():
    context = status(packet_text().replace('SETTLEMENT="WIN_LOSE";\n', "", 1))
    assert context.status == "PASS"
    assert any(row["rule_id"] == "SEM_1X2_WIN_LOSE_V1" for row in context.semantic_resolutions)


def test_empty_exact_1x2_settlement_is_canonically_resolved():
    context = status(packet_text().replace('SETTLEMENT="WIN_LOSE";', 'SETTLEMENT="";', 1))
    assert context.status == "PASS"
    assert any(row["origin"] == "CANONICALLY_DERIVED" for row in context.semantic_resolutions)


def test_truncated_odd_is_blocked():
    context = status(packet_text().rsplit("}", 1)[0])
    assert context.status == "BLOCKED"
    assert any(reason.startswith("TRUNCATED_ODD_BLOCK") for reason in context.blocked_reasons)


def test_mixed_event_team_owner_is_blocked():
    text = packet_text().replace('MARKET="Liczba goli - Home FC";\nPERIOD="FULL_TIME";\nOWNER="Home FC";', 'MARKET="Liczba goli - Home FC";\nPERIOD="FULL_TIME";\nOWNER="Other FC";', 1)
    context = status(text)
    assert context.status == "PASS_WITH_QUARANTINE"
    assert any("TEAM_TOTAL_OWNER_CONFLICT_HOME" in row["reasons"] for row in context.quarantined_rows)


def test_legacy_event_status_without_positive_readiness_remains_fail_closed():
    text = packet_text().replace('ANALYSIS_READY="YES";\n', "").replace('CLEAN_CORE_READY="YES";\n', "").replace('FULL_USABLE_READY="YES";', 'EVENT_STATUS="GOTOWE";')
    context = status(text)
    assert context.status == "BLOCKED"
    assert "ENGINE_RECONSTRUCTED_CORE_WITHOUT_POSITIVE_EXTRACTOR_READINESS" not in context.warnings


def test_explicit_count_mismatch_is_blocked():
    context = status(packet_text().replace("ODDS_COUNT=9;", "ODDS_COUNT=8;"))
    assert context.status == "BLOCKED"


def test_malformed_match_identity_is_blocked():
    context = status(packet_text().replace("Home FC - Away FC", "Unknown event"))
    assert context.status == "BLOCKED"
    assert "MATCH_TEAMS_NOT_UNAMBIGUOUS" in context.blocked_reasons


def test_render_is_deterministic_three_times():
    outputs = [render_json(status(packet_text())) for _ in range(3)]
    assert outputs[0] == outputs[1] == outputs[2]


def test_schema_after_semantic_normalization():
    schema_path = Path(__file__).parents[1] / "schemas" / "apex_context_packet.schema.json"
    normalized = packet_text().replace('PARSER_TRUTH_STATUS="PASS";', 'PARSER_TRUTH_STATUS="PARTIAL";').replace('EXHAUSTIVE_READY="YES";', 'EXHAUSTIVE_READY="NO";')
    payload = json.loads(render_json(status(normalized)))
    jsonschema.validate(payload, json.loads(schema_path.read_text(encoding="utf-8")))
