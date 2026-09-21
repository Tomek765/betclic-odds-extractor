import copy, unittest
from provider_final_state_v0_1 import ProviderFinalStateError, normalize_final_response

RAW={"logical_path":"provider_response.bin","sha256":"a"*64}
def evidence():
 return {"response_type":"offering.access.api.GetMatchResponse","raw_stream_sha256":"a"*64,"schema_source_sha256":"b"*64,
 "decoded_response":{"response":{"oneofKind":"payload","payload":{"match":{"matchId":"42","isLive":False,"scoreboard":{"matchId":"42","liveDisplayStatus":3,"currentScore":{"contestant1":"2","contestant2":"1"}}}}}}}
class ProviderFinalStateTests(unittest.TestCase):
 def test_normalizes_exact_runtime_decoded_final_state(self):
  out=normalize_final_response(expected_provider_event_id="42",decoded_evidence=evidence(),raw_source=RAW,observed_at="2026-08-30T18:00:00Z",assignment_candidate_ids=["42"])
  self.assertEqual((out["match_status"],out["home_score_ft"],out["away_score_ft"]),("FINAL",2,1))
 def test_empty_body_missing_final_state_and_incomplete_stream_fail_closed(self):
  for mutation in (lambda x:x.pop("decoded_response"),lambda x:x["decoded_response"]["response"].update({"oneofKind":"notifications"}),lambda x:x["decoded_response"]["response"]["payload"]["match"]["scoreboard"].pop("currentScore")):
   item=evidence(); mutation(item)
   with self.assertRaises(ProviderFinalStateError): normalize_final_response(expected_provider_event_id="42",decoded_evidence=item,raw_source=RAW,observed_at="2026-08-30T18:00:00Z",assignment_candidate_ids=["42"])
 def test_foreign_and_ambiguous_assignment_fail_closed(self):
  item=evidence(); item["decoded_response"]["response"]["payload"]["match"]["scoreboard"]["matchId"]="43"
  with self.assertRaises(ProviderFinalStateError): normalize_final_response(expected_provider_event_id="42",decoded_evidence=item,raw_source=RAW,observed_at="2026-08-30T18:00:00Z",assignment_candidate_ids=["42"])
  with self.assertRaises(ProviderFinalStateError): normalize_final_response(expected_provider_event_id="42",decoded_evidence=evidence(),raw_source=RAW,observed_at="2026-08-30T18:00:00Z",assignment_candidate_ids=["42","43"])
 def test_live_or_missing_final_state_fail_closed(self):
  for mutation in (lambda x:x["decoded_response"]["response"]["payload"]["match"].update({"isLive":True}),lambda x:x["decoded_response"]["response"]["payload"]["match"]["scoreboard"].update({"liveDisplayStatus":2})):
   item=evidence(); mutation(item)
   with self.assertRaises(ProviderFinalStateError): normalize_final_response(expected_provider_event_id="42",decoded_evidence=item,raw_source=RAW,observed_at="2026-08-30T18:00:00Z",assignment_candidate_ids=["42"])
