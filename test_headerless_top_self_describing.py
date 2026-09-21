"""Real Top cards retain complete semantics in the selection label."""
import json
import unittest
from pathlib import Path
from parser import recover_headerless_top_offer, parse_market_record
from core import partition_semantic_records


class HeaderlessSelfDescribing(unittest.TestCase):
    def test_original_rows_are_classified_with_price_and_lineage_preserved(self):
        cases = json.loads((Path(__file__).parent / "tests_context/fixtures/headerless_top_self_describing.json").read_text(encoding="utf-8"))
        expected = ["GOALS_OU", "GOALSCORER", "EVENT_RESULT", "GOAL_MARGIN",
                    "TEAM_TOTALS_AWAY", "FIRST_GOAL_TEAM", "PLAYER_PROP", "PLAYER_PROP_XTRA"]
        index = 0
        for case in cases:
            for source in case["rows"]:
                with self.subTest(source=source["raw_record_id"]):
                    home, away = source["event_id"].split("|")
                    recovered = recover_headerless_top_offer(source["selection"], source["tab_name"], source["market_instance_id"], home, away)
                    self.assertIsNotNone(recovered)
                    row, issue = parse_market_record(
                        category="Top", market_title=recovered["market_title"],
                        raw_selection=recovered["raw_selection"], odds_str=source["odds"],
                        raw_text=source["raw"], section_title="", home_team=home, away_team=away,
                        participant_hint=recovered.get("participant_hint"), container_id=source["market_instance_id"],
                        raw_record_id=source["raw_record_id"], source_raw_record_ids=source["source_raw_record_ids"],
                    )
                    self.assertIsNone(issue)
                    self.assertEqual(row["FAMILY"], expected[index])
                    self.assertEqual(float(row["ODDS"]), float(source["odds"]))
                    self.assertEqual(row["RAW"], source["raw"])
                    self.assertEqual(row["source_raw_record_ids"], source["source_raw_record_ids"])
                    if index == 7:
                        self.assertEqual(partition_semantic_records([row]), ([], [row]))
                index += 1

    def test_non_betting_and_other_sections_are_not_recovered(self):
        instance = "tab:Top|div[market-box#0]>sports-matrix-markets[#1]>bcdk-bet-button-wrapper[#0]>button[market-selection#0]"
        self.assertIsNone(recover_headerless_top_offer("1.85", "Top", instance))
        self.assertIsNone(recover_headerless_top_offer("Poniżej 2,5 goli w meczu", "Statystyki", instance))
        self.assertIsNone(recover_headerless_top_offer("Poniżej 2,5 goli w meczu", "Top", "statistics-table"))
        self.assertIsNone(recover_headerless_top_offer("Poniżej 2,5 goli w meczu i obie drużyny strzelą", "Top", instance))
        self.assertIsNone(recover_headerless_top_offer("Napoli i Arsenal powyżej 1,5 goli w meczu", "Top", instance, "Napoli", "Arsenal"))
        self.assertIsNone(recover_headerless_top_offer("Kai Havertz lub Bukayo Saka lub jego zmiennik strzeli gola w meczu", "Top", instance))
