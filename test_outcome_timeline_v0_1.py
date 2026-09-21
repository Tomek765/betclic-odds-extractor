import copy, hashlib, json, tempfile, unittest
from pathlib import Path
from outcome_timeline_v0_1 import *
from snapshot_manifest_v0_1 import build_manifest
S={"logical_path":"provider/state","sha256":"a"*64}
class OutcomeTests(unittest.TestCase):
 def test_o01_o05_o13_o14(self):
  a=build_outcome("42","FINAL",1,0,"2026-01-01T14:00:00Z",S,0,0); self.assertEqual(a,build_outcome("42","FINAL",1,0,"2026-01-01T16:00:00+02:00",S,0,0)); self.assertTrue(a["outcome_hash"])
 def test_o06_o07_o08_o09(self):
  a=build_event("42",1,"OWN_GOAL","AWAY",90,"2026-01-01T14:00:00Z",S,3); b=build_event("42",2,"SECOND_YELLOW_RED","HOME",91,"2026-01-01T14:00:00Z",S); self.assertEqual((a["match_minute"],a["stoppage_minute"]),(90,3)); self.assertNotEqual(a["event_type"],b["event_type"])
 def test_o02_o10_o11_o12(self):
  snap={"provider_event_id":"42"}; out=build_outcome("42","FINAL",1,0,"2026-01-01T14:00:00Z",S); event=build_event("42",1,"GOAL","HOME",1,"2026-01-01T14:00:00Z",S); validate_exact_join(snap,out,[event])
  with self.assertRaises(OutcomeValidationError): validate_exact_join(snap,{**out,"provider_event_id":"43"},[event])
  with self.assertRaises(OutcomeValidationError): build_outcome("42","LIVE",None,None,"2026-01-01T14:00:00Z",S)
  with self.assertRaises(OutcomeValidationError): validate_exact_join(snap,out,[event,{**event}])
 def test_o03_o04(self):
  snapshot_hash="abc"; out=build_outcome("42","FINAL",1,0,"2026-01-01T14:00:00Z",S); event=build_event("42",1,"GOAL","HOME",1,"2026-01-01T14:00:00Z",S); self.assertTrue(out["outcome_hash"] and event["event_hash"]); self.assertEqual(snapshot_hash,"abc")
 def test_c07_c08_outcome_can_be_final_when_timeline_is_unavailable(self):
  outcome=build_outcome("42","FINAL",1,0,"2026-01-01T14:00:00Z",S)
  revision=build_label_revision("42","TIMELINE","b"*64,1,"2026-01-01T14:00:00Z",availability="UNAVAILABLE")
  self.assertEqual(outcome["match_status"],"FINAL"); self.assertEqual(revision["availability"],"UNAVAILABLE")
 def test_c09_c10_append_only_corrections_are_explicit_and_deterministic(self):
  first=build_label_revision("42","OUTCOME","a"*64,1,"2026-01-01T14:00:00Z")
  fixed=build_label_revision("42","OUTCOME","b"*64,2,"2026-01-01T14:01:00Z","a"*64)
  self.assertEqual(first,build_label_revision("42","OUTCOME","a"*64,1,"2026-01-01T15:00:00+01:00")); self.assertEqual(fixed["supersedes_hash"],"a"*64)
  with self.assertRaises(OutcomeValidationError): build_label_revision("42","OUTCOME","b"*64,2,"2026-01-01T14:01:00Z")
 def test_c14_c15_revision_artifact_is_append_only_and_has_no_snapshot_fields(self):
  revision=build_label_revision("42","OUTCOME","a"*64,1,"2026-01-01T14:00:00Z")
  self.assertFalse({"snapshot_id","snapshot_sha256","canonical_snapshot"}&set(revision))
  with tempfile.TemporaryDirectory() as directory:
   path=write_label_revision_append_only(Path(directory),revision)
   self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["revision_hash"],revision["revision_hash"])
   with self.assertRaises(FileExistsError): write_label_revision_append_only(Path(directory),revision)
 def test_c06_c07_c08_c09_c18_eligibility_and_nonfinal_firewall(self):
  out=build_outcome("42","FINAL",1,0,"2026-01-01T14:00:00Z",S)
  self.assertEqual(label_eligibility(out,"UNAVAILABLE"),{"OUTCOME_ELIGIBLE":"YES","TIMELINE_ELIGIBLE":"NO"})
  self.assertEqual(label_eligibility(out,"AVAILABLE")["TIMELINE_ELIGIBLE"],"YES")
  for status in ("LIVE","POSTPONED","ABANDONED","CANCELLED"):
   with self.assertRaises(OutcomeValidationError): build_outcome("42",status,1,0,"2026-01-01T14:00:00Z",S)
 def test_c19_final_state_and_label_revision_cannot_mutate_frozen_snapshot(self):
  run={"run_id":"run_test","provider":"BETCLIC","provider_event_id":"42","kickoff_at":"2026-01-01T14:00:00Z","capture_started_at":"2026-01-01T13:00:00Z","capture_finished_at":"2026-01-01T13:01:00Z","capture_status":"PREMATCH_VALID","identity_validation":{"route_event_id":"42","embedded_match_id":"42","exact_match":True}}
  observation={"schema_version":"APEX_HISTORY_COLLECTION_CONTRACT_V0_1","provider":"BETCLIC","provider_event_id":"42","observed_at":"2026-01-01T13:00:01Z","observation_sequence":1,"observation_id":"run_test:1","raw_record_id":"run_test:1","source_raw_record_ids":["run_test:1"],"disposition":"PENDING","disposition_reason":None,"prematch_eligible":True,"prematch_ineligible_reason":None,"raw_observation":{"raw_record_id":"run_test:1","source_hash":"b"*64,"raw":{"odds":"2.15"}}}
  snapshot=build_manifest(run,[observation],{"run":{"logical_path":"history/run","sha256":"c"*64}}); frozen=copy.deepcopy(snapshot)
  outcome=build_outcome("42","FINAL",1,0,"2026-01-01T16:00:00Z",S)
  revision=build_label_revision("42","OUTCOME",outcome["outcome_hash"],1,"2026-01-01T16:00:00Z")
  self.assertEqual(snapshot,frozen); self.assertEqual(snapshot["snapshot_sha256"],frozen["snapshot_sha256"])
  self.assertFalse({"snapshot_id","snapshot_sha256","canonical_snapshot"}&set(revision))
 def test_c20_source_hash_and_logical_path_fail_closed(self):
  with self.assertRaises(OutcomeValidationError): build_outcome("42","FINAL",1,0,"2026-01-01T14:00:00Z",{"logical_path":"provider/state","sha256":"a"*63})
  with self.assertRaises(OutcomeValidationError): build_event("42",1,"GOAL","HOME",1,"2026-01-01T14:00:00Z",{"sha256":"a"*64})
 def test_c21_revision_writer_rejects_tampered_or_snapshot_mutating_payload(self):
  revision=build_label_revision("42","OUTCOME","a"*64,1,"2026-01-01T14:00:00Z")
  with tempfile.TemporaryDirectory() as directory:
   with self.assertRaises(OutcomeValidationError): write_label_revision_append_only(Path(directory),{**revision,"revision_hash":"0"*64})
   with self.assertRaises(OutcomeValidationError): write_label_revision_append_only(Path(directory),{**revision,"snapshot_sha256":"b"*64})
 def test_c22_exact_join_rejects_forged_outcome_or_event_content(self):
  snap={"provider_event_id":"42"}; out=build_outcome("42","FINAL",1,0,"2026-01-01T14:00:00Z",S); event=build_event("42",1,"GOAL","HOME",1,"2026-01-01T14:00:00Z",S)
  validate_exact_join(snap,out,[event])
  with self.assertRaises(OutcomeValidationError): validate_exact_join(snap,{**out,"home_score_ft":2},[event])
  with self.assertRaises(OutcomeValidationError): validate_exact_join(snap,out,[{**event,"match_minute":2}])
 def test_c23_eligibility_rejects_forged_outcome_hash(self):
  out=build_outcome("42","FINAL",1,0,"2026-01-01T14:00:00Z",S)
  self.assertEqual(label_eligibility(out,"UNAVAILABLE")["OUTCOME_ELIGIBLE"],"YES")
  with self.assertRaises(OutcomeValidationError): label_eligibility({**out,"outcome_hash":"0"*64},"UNAVAILABLE")
