"""Ordered half/full components need bounded, unambiguous team matching."""
import unittest
import json
from pathlib import Path

from parser import parse_market_record


def parse(selection, home="Chlef", away="CR Belouizdad"):
    return parse_market_record(
        category="Wynik", market_title="Wynik Meczu Połowa / Cały",
        raw_selection=selection, odds_str="55", raw_text=f"{selection} 55",
        section_title="", home_team=home, away_team=away,
        container_id="half-full", raw_record_id="fixture:1",
        source_raw_record_ids=["fixture:1"],
    )[0]


class HalfFullComponentAlias(unittest.TestCase):
    def test_original_capture_alias_keeps_source_identity_and_price(self):
        fixture = json.loads((Path(__file__).parent / "tests_context" / "fixtures" /
                              "half_full_alias_real.json").read_text(encoding="utf-8"))
        source = next(row for row in fixture["rows"] if row["selection"] == "Belouizdad / Chlef")
        home, away = source["event_id"].split("|")
        row, issue = parse_market_record(
            category=source["category"], market_title=source["market"],
            raw_selection=source["selection"], odds_str=source["odds"],
            raw_text=source["raw"], section_title=source["section_title"],
            home_team=home, away_team=away, container_id=source["market_instance_id"],
            raw_record_id=source["raw_record_id"], source_raw_record_ids=source["source_raw_record_ids"],
        )
        self.assertIsNone(issue)
        self.assertEqual((row["SELECTION"], row["SETTLEMENT"]), ("AWAY_HOME", "WIN_LOSE"))
        self.assertEqual(float(row["ODDS"]), float(source["odds"]))
        self.assertEqual(row["source_raw_record_ids"], source["source_raw_record_ids"])

    def test_each_component_resolves_alias_without_losing_order(self):
        for text, expected in {
            "Belouizdad / Chlef": "AWAY_HOME",
            "Chlef / Belouizdad": "HOME_AWAY",
            "Remis / Belouizdad": "DRAW_AWAY",
            "Belouizdad / Belouizdad": "AWAY_AWAY",
        }.items():
            with self.subTest(text=text):
                row = parse(text)
                self.assertEqual(row["SELECTION"], expected)
                self.assertEqual(row["SETTLEMENT"], "WIN_LOSE")
                self.assertEqual(row["source_raw_record_ids"], ["fixture:1"])
                self.assertIn(text, row.get("RAW_ORIGINAL") or row["RAW"])

    def test_ambiguous_shared_alias_stays_unconfirmed(self):
        row = parse("United / Remis", "FC United", "AC United")
        self.assertEqual(row["SETTLEMENT"], "UNKNOWN")

    def test_substring_of_other_team_is_not_home(self):
        row = parse("York City / York", "York", "York City")
        self.assertEqual(row["SELECTION"], "AWAY_HOME")

    def test_unrecognized_extra_words_stay_unconfirmed(self):
        row = parse("Not Chlef / Remis")
        self.assertEqual(row["SETTLEMENT"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
