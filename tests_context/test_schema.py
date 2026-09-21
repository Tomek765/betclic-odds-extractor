import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")

from apex_context_engine.engine import build_context
from apex_context_engine.packet_parser import parse_packet_file

ROOT = Path(__file__).parents[1]


def test_json_schema():
    fixture = Path(__file__).parent / "fixtures" / "minimal_packet.txt"
    schema = json.loads((ROOT / "schemas" / "apex_context_packet.schema.json").read_text(encoding="utf-8"))
    payload = build_context(parse_packet_file(fixture)).to_dict()
    jsonschema.validate(payload, schema)
