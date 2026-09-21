"""Bounded short-name forms observed in saved native Betclic contestants."""
import unittest
import json
from pathlib import Path
from parser import parse_market_record
from test_half_full_component_alias import parse


class HalfFullNativeShortNames(unittest.TestCase):
    def test_original_rows_with_native_short_name_evidence(self):
        cases = json.loads((Path(__file__).parent / "tests_context/fixtures/half_full_native_short_names.json").read_text(encoding="utf-8"))
        for case in cases:
            self.assertTrue(case["rows"])
            for source in case["rows"]:
                home, away = source["event_id"].split("|")
                expected = []
                for component in source["selection"].split("/"):
                    name = component.strip()
                    if name == case["short_name"]:
                        name = case["full_name"]
                    expected.append("HOME" if name == home else "AWAY" if name == away else "DRAW" if name == "Remis" else "UNPROVEN")
                self.assertNotIn("UNPROVEN", expected)
                row, issue = parse_market_record(
                    category=source["category"], market_title=source["market"],
                    raw_selection=source["selection"], odds_str=source["odds"], raw_text=source["raw"],
                    section_title=source["section_title"], home_team=home, away_team=away,
                    container_id=source["market_instance_id"], raw_record_id=source["raw_record_id"],
                    source_raw_record_ids=source["source_raw_record_ids"],
                )
                self.assertIsNone(issue)
                self.assertEqual(row["SELECTION"], "_".join(expected))
                self.assertEqual(row["SETTLEMENT"], "WIN_LOSE")
                self.assertEqual(float(row["ODDS"]), float(source["odds"]))
                self.assertEqual(row["source_raw_record_ids"], source["source_raw_record_ids"])

    def test_native_club_prefix(self):
        row = parse("Platense / Platense", "CA Platense", "Deportivo Riestra")
        self.assertEqual((row["SELECTION"], row["SETTLEMENT"]), ("HOME_HOME", "WIN_LOSE"))

    def test_native_club_suffix(self):
        row = parse("Olympiakos Nikozja / Pafos", "Pafos FC", "Olympiakos Nikozja")
        self.assertEqual((row["SELECTION"], row["SETTLEMENT"]), ("AWAY_HOME", "WIN_LOSE"))

    def test_native_united_abbreviation(self):
        row = parse("Sheffield Utd / Blackburn", "Blackburn", "Sheffield United")
        self.assertEqual((row["SELECTION"], row["SETTLEMENT"]), ("AWAY_HOME", "WIN_LOSE"))

    def test_shared_short_name_is_ambiguous(self):
        self.assertEqual(parse("Pafos / Remis", "Pafos FC", "Pafos SC")["SETTLEMENT"], "UNKNOWN")

    def test_age_and_womens_markers_are_preserved(self):
        for home, away in [("Pafos FC U21", "Pafos FC U19"), ("Pafos FC K.", "Pafos FC")]:
            with self.subTest(home=home, away=away):
                row = parse("Pafos / Remis", home, away)
                if "U21" in home:
                    self.assertEqual(row["SETTLEMENT"], "UNKNOWN")
                else:
                    self.assertEqual(row["SELECTION"], "AWAY_DRAW")

    def test_city_and_regional_words_are_not_silently_removed(self):
        for home in ["Pafos City", "Pafos RS", "Pafos Utd U21"]:
            with self.subTest(home=home):
                self.assertEqual(parse("Pafos / Remis", home, "Other Team")["SETTLEMENT"], "UNKNOWN")
