import json
from pathlib import Path

from apex_context_engine.engine import build_context
from apex_context_engine.packet_parser import parse_packet_file, parse_packet_text
from apex_context_engine.report import write_outputs

FIXTURE = Path(__file__).parent / "fixtures" / "minimal_packet.txt"


def test_parser_extracts_header_and_odds():
    packet = parse_packet_file(FIXTURE)
    assert packet.header["MATCH"] == "Home FC - Away FC"
    assert len(packet.odds) == 9
    assert not packet.errors


def test_parser_preserves_scorer_provenance_and_event_identity():
    packet = parse_packet_text('''BETCLIC_FULL_ODDS_PACKET{
MATCH="Home FC - Away FC";
COMPETITION="Test";
}
ODD{
CATEGORY="Strzelcy";
FAMILY="GOALSCORER";
MARKET="Pierwszy strzelec";
PERIOD="FULL_TIME";
OWNER="Home FC";
SELECTION="Jan Kowalski";
LINE="";
SETTLEMENT="WIN_LOSE";
ODDS="4.00";
RAW="Jan Kowalski 4.00";
SCORER_SCOPE="FIRST_GOAL";
PARTICIPANT="Jan Kowalski";
SOURCE_RAW_RECORD_IDS="capture:10,capture:11,capture:10";
MARKET_INSTANCE_ID="tab:Strzelcy|row:1";
}
''')
    record = packet.odds[0]
    assert record.participant == "Jan Kowalski"
    assert record.source_raw_record_ids == ("capture:10", "capture:11")
    assert record.event_teams == ("Home FC", "Away FC")


def test_engine_is_deterministic():
    packet = parse_packet_file(FIXTURE)
    first = build_context(packet).to_dict()
    second = build_context(packet).to_dict()
    assert first == second


def test_context_has_market_script_and_offense_map():
    context = build_context(parse_packet_file(FIXTURE))
    assert context.status == "PASS"
    assert context.market_script["lambda_home"] is not None
    assert context.market_script["lambda_away"] is not None
    assert context.offense_map["status"] == "READY"


def test_output_files(tmp_path):
    context = build_context(parse_packet_file(FIXTURE))
    json_path, text_path = write_outputs(context, tmp_path)
    assert json_path.exists()
    assert text_path.exists()
    loaded = json.loads(json_path.read_text(encoding="utf-8"))
    assert loaded["schema_version"] == "1.0.0"
    assert loaded["status"] == "PASS"


def test_fail_closed_missing_packet():
    try:
        parse_packet_text("not a packet")
    except ValueError:
        pass
    else:
        raise AssertionError("Expected parser to fail closed")
