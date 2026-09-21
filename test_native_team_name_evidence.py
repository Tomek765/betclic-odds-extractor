import json
import unittest
import tempfile
from pathlib import Path
from team_name_evidence import extract_native_team_names, saved_native_team_names
from parser import parse_market_record


def html(match_id="123", short="Example"):
    return '<script id="ng-state" type="application/json">' + json.dumps({"data": {
        "matchId": match_id, "contestants": [{"name": "Club Example City", "shortName": short},
                                               {"name": "Other Team", "shortName": "Other"}]}}) + '</script>'


class NativeTeamNameEvidence(unittest.TestCase):
    def test_result_tab_is_distinct_from_exact_score_on_windows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "snapshots").mkdir()
            (root / "snapshots/tab_run_123_456_2_Wynik.html").write_text(html(), encoding="utf-8")
            (root / "snapshots/tab_run_123_456_5_Dok_adny_wynik.html").write_text(html("999"), encoding="utf-8")
            evidence = saved_native_team_names(root / "diagnostics/raw_before_dedupe_run_123_456.jsonl", "Club Example City", "Other Team")
            self.assertEqual(evidence["event_id"], "123")

    def test_exact_event_native_alias_resolves_ordered_pair(self):
        evidence = extract_native_team_names(html(), "Club Example City", "Other Team", "123")
        row, issue = parse_market_record(category="Wynik", market_title="Wynik Meczu Połowa / Cały",
            raw_selection="Other / Example", odds_str="55", raw_text="Other / Example 55",
            section_title="", home_team="Club Example City", away_team="Other Team", container_id="bounded",
            native_team_names=evidence)
        self.assertIsNone(issue)
        self.assertEqual((row["SELECTION"], row["SETTLEMENT"]), ("AWAY_HOME", "WIN_LOSE"))

    def test_foreign_event_and_reversed_participants_are_rejected(self):
        self.assertEqual(extract_native_team_names(html(), "Club Example City", "Other Team", "456"), {})
        self.assertEqual(extract_native_team_names(html(), "Other Team", "Club Example City"), {})

    def test_missing_state_is_not_recovered_from_unscoped_text(self):
        self.assertEqual(extract_native_team_names('"name":"Club Example City","shortName":"Example"', "Club Example City", "Other Team"), {})

    def test_conflicting_native_matches_are_rejected(self):
        first = json.loads(html().split('>', 1)[1].split('</script>', 1)[0])
        second = json.loads(html("456", "Different").split('>', 1)[1].split('</script>', 1)[0])
        document = '<script id="ng-state">' + json.dumps([first, second]) + '</script>'
        self.assertEqual(extract_native_team_names(document, "Club Example City", "Other Team"), {})
