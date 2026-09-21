import unittest

from history_contract_v0_1 import (
    build_history_observation,
    canonicalize_utc_datetime,
    evaluate_capture_status,
    extract_embedded_provider_match_info,
    parse_betclic_route_event_id,
)


URL = "https://www.betclic.pl/pilka-nozna-sfootball/la-liga-c7/elche-barcelona-m1186317424689152"
MATCH_ID = "1186317424689152"
KICKOFF = "2026-08-23T19:30:00.0000000Z"


def embedded(*, match_id=MATCH_ID, kickoff=KICKOFF, is_live=False):
    return {"provider_match_id": match_id, "match_date_utc": kickoff, "is_live": is_live}


class HistoryContractV01Tests(unittest.TestCase):
    def test_t03_quote_before_kickoff_is_eligible(self):
        row = build_history_observation({"raw_record_id": "run:1", "odds": "2.00"}, MATCH_ID, KICKOFF, "2026-08-23T19:29:59.000000Z", 1)
        self.assertTrue(row["prematch_eligible"])

    def test_t04_quote_at_or_after_kickoff_is_preserved_but_ineligible(self):
        raw = {"raw_record_id": "run:1", "odds": "2.00", "record_type": "ODD"}
        row = build_history_observation(raw, MATCH_ID, KICKOFF, "2026-08-23T19:30:00.000000Z", 1)
        self.assertFalse(row["prematch_eligible"])
        self.assertEqual(row["prematch_ineligible_reason"], "QUOTE_AT_OR_AFTER_KICKOFF")
        self.assertEqual(row["raw_observation"], raw)

    def test_t05_live_provider_is_rejected(self):
        status = evaluate_capture_status(MATCH_ID, embedded(is_live=True), "PREMATCH", "2026-08-23T19:00:00.000000Z")
        self.assertEqual(status["capture_status"], "LIVE_REJECTED")

    def test_t06_missing_provider_id_is_unsafe(self):
        status = evaluate_capture_status(None, embedded(), "PREMATCH", "2026-08-23T19:00:00.000000Z")
        self.assertEqual(status["capture_status"], "IDENTITY_UNSAFE")

    def test_t06b_mismatched_ids_are_unsafe(self):
        status = evaluate_capture_status("123", embedded(match_id="456"), "PREMATCH", "2026-08-23T19:00:00.000000Z")
        self.assertEqual(status["capture_status"], "IDENTITY_UNSAFE")

    def test_t07_missing_naive_or_invalid_kickoff_is_unsafe(self):
        for value in (None, "2026-08-23T19:30:00", "not-a-date"):
            with self.subTest(value=value):
                status = evaluate_capture_status(MATCH_ID, embedded(kickoff=value), "PREMATCH", "2026-08-23T19:00:00.000000Z")
                self.assertEqual(status["capture_status"], "TIME_UNSAFE")

    def test_t07b_z_datetime_is_canonical_utc(self):
        self.assertEqual(canonicalize_utc_datetime(KICKOFF), "2026-08-23T19:30:00.000000Z")

    def test_t07c_capture_started_at_or_after_kickoff_is_not_prematch_valid(self):
        status = evaluate_capture_status(MATCH_ID, embedded(), "PREMATCH", "2026-08-23T19:30:00.000000Z")
        self.assertEqual(status["capture_status"], "TIME_UNSAFE")

    def test_t11_raw_lineage_is_preserved_for_pending_disposition(self):
        raw = {"raw_record_id": "run:7", "source_raw_record_ids": ["run:7"], "record_type": "ODD"}
        row = build_history_observation(raw, MATCH_ID, KICKOFF, "2026-08-23T19:00:00.000000Z", 7)
        self.assertEqual(row["disposition"], "PENDING")
        self.assertEqual(row["raw_observation"]["source_raw_record_ids"], ["run:7"])

    def test_t12_exact_duplicates_remain_distinct(self):
        raw = {"raw_record_id": "run:1", "odds": "2.00"}
        first = build_history_observation(raw, MATCH_ID, KICKOFF, "2026-08-23T19:00:00.000000Z", 1)
        second = build_history_observation(raw, MATCH_ID, KICKOFF, "2026-08-23T19:00:00.000000Z", 2)
        self.assertNotEqual(first["observation_sequence"], second["observation_sequence"])
        self.assertEqual(first["raw_observation"], second["raw_observation"])

    def test_t18_false_provider_and_unknown_preflight_is_unsafe(self):
        status = evaluate_capture_status(MATCH_ID, embedded(), "UNKNOWN", "2026-08-23T19:00:00.000000Z")
        self.assertEqual(status["capture_status"], "STATUS_UNSAFE")

    def test_t19_false_provider_and_live_preflight_is_unsafe(self):
        status = evaluate_capture_status(MATCH_ID, embedded(), "LIVE", "2026-08-23T19:00:00.000000Z")
        self.assertEqual(status["capture_status"], "STATUS_UNSAFE")

    def test_t20_route_parser_extracts_exact_id(self):
        self.assertEqual(parse_betclic_route_event_id(URL), MATCH_ID)

    def test_t21_route_parser_rejects_missing_or_ambiguous_ids(self):
        self.assertIsNone(parse_betclic_route_event_id("https://www.betclic.pl/pilka-nozna"))
        self.assertIsNone(parse_betclic_route_event_id(URL + "/other-m999"))

    def test_embedded_provider_match_info_requires_single_values(self):
        html = '{"matchId":"1186317424689152","matchDateUtc":"2026-08-23T19:30:00.0000000Z","isLive":false}'
        self.assertEqual(extract_embedded_provider_match_info(html), embedded())


if __name__ == "__main__":
    unittest.main()
