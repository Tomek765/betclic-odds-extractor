from __future__ import annotations
import copy, json, tempfile, unittest
from pathlib import Path
from disposition_ledger_v0_1 import *
from snapshot_manifest_v0_1 import build_manifest

def manifest():
    run={"run_id":"r","provider":"BETCLIC","provider_event_id":"42","kickoff_at":"2026-01-01T12:00:00Z","capture_started_at":"2026-01-01T10:00:00Z","capture_finished_at":"2026-01-01T10:01:00Z","capture_status":"PREMATCH_VALID","identity_validation":{"exact_match":True}}
    def row(n):
        i=f"r:{n}"; return {"provider_event_id":"42","observed_at":"2026-01-01T10:00:01Z","observation_sequence":n,"observation_id":i,"raw_record_id":i,"prematch_eligible":True,"disposition":"PENDING","raw_observation":{"raw_record_id":i,"source_hash":"a"*64,"raw":{"odds":"2.15"}}}
    return build_manifest(run,[row(1),row(2)],{"test":{"logical_path":"test","sha256":"b"*64}})
def ann(m, occ, decision="ACCEPTED", reason="OK", supersedes=None):
    return create_annotation(m,occ,decision,reason,"TEST","TEST_STAGE","2026-01-01T13:00:00+00:00",{"logical_path":"decision/test","sha256":"c"*64},supersedes_annotation_id=supersedes)
class LedgerTests(unittest.TestCase):
 def test_d01_d02_d03_d07_d08(self):
    m=manifest(); a=ann(m,m["canonical_snapshot"]["observations"][0]["occurrence_id"]); self.assertEqual(a,ann(m,a["occurrence_id"])); self.assertNotEqual(a["occurrence_id"],m["canonical_snapshot"]["observations"][1]["occurrence_id"]); self.assertEqual(m["snapshot_sha256"],copy.deepcopy(m)["snapshot_sha256"]); self.assertEqual(a["decision"],"ACCEPTED")
 def test_d04_d11_d12(self):
    m=manifest()
    with self.assertRaises(LedgerValidationError): ann(m,"missing")
    a=ann(m,m["canonical_snapshot"]["observations"][0]["occurrence_id"]); bad={**a,"provider_event_id":"other"}
    with self.assertRaises(LedgerValidationError): validate_append(m,[],bad)
 def test_d05_d06_d09_d10(self):
    m=manifest(); a=ann(m,m["canonical_snapshot"]["observations"][0]["occurrence_id"]); b=ann(m,a["occurrence_id"],"REJECTED","BAD",a["annotation_id"])
    with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as d:
      p=Path(d)/"ledger.jsonl"; first=append_annotation(p,m,a); second=append_annotation(p,m,b); self.assertNotEqual(first,second); rows=load_ledger(p); self.assertEqual(active_annotations(rows)[a["occurrence_id"]]["annotation_id"],b["annotation_id"])
      with self.assertRaises(LedgerValidationError): append_annotation(p,m,ann(m,a["occurrence_id"],"QUARANTINED","X"))
 def test_d13_real_snapshot_unchanged(self):
    p=Path(__file__).parent/"diagnostics/history_v0_1/manifests/history_snapshot_manifest_run_1787949287_1344.json"; m=json.loads(p.read_text(encoding="utf-8")); before=m["snapshot_sha256"]; a=ann(m,m["canonical_snapshot"]["observations"][0]["occurrence_id"]); self.assertTrue(a["annotation_id"]); self.assertEqual(before,m["snapshot_sha256"])
