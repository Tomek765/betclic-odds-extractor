"""Corners and card points are event totals, never goal totals."""
import unittest
from pathlib import Path

from core import partition_semantic_records
from parser import parse_market_record
from replay import replay_real_prematch


def parse(title: str, selection: str):
    return parse_market_record(
        category="Statystyki", market_title=title, raw_selection=selection,
        odds_str="1.90", raw_text=f"{selection} 1.90", section_title="",
        home_team="Elche", away_team="Barcelona", container_id="bounded-stat",
        main_tab="Statystyki", market_instance_id="tab:Statystyki|row#0",
        raw_record_id="real:1", source_raw_record_ids=["real:1"],
    )


class NonGoalEventTotalFalseAccept(unittest.TestCase):
    def test_first_half_corners_are_event_total(self):
        row, issue = parse("1. połowa - Rzuty rożne", "Powyżej 4,5")
        self.assertIsNone(issue)
        self.assertEqual((row["FAMILY"], row["SELECTION"], row["LINE"], row["PERIOD"],
                          row["SETTLEMENT"]),
                         ("EVENT_TOTAL", "OVER", "4.5", "1ST_HALF", "NO_PUSH"))
        self.assertEqual(partition_semantic_records([row]), ([row], []))

    def test_first_half_card_count_is_event_total(self):
        row, issue = parse("Liczba Kartek 1. połowa", "Poniżej 3,5")
        self.assertIsNone(issue)
        self.assertEqual((row["FAMILY"], row["SELECTION"], row["LINE"], row["PERIOD"]),
                         ("EVENT_TOTAL", "UNDER", "3.5", "1ST_HALF"))

    def test_unscoped_card_points_stop_false_full_time_accept(self):
        row, issue = parse("Punkty za kartki Powyżej/Poniżej", "Powyżej 45,5")
        self.assertIsNone(issue)
        self.assertEqual((row["FAMILY"], row["SELECTION"], row["LINE"], row["PERIOD"],
                          row["SETTLEMENT"]),
                         ("EVENT_TOTAL", "OVER", "45.5", "UNKNOWN", "NO_PUSH"))
        self.assertEqual(partition_semantic_records([row]), ([], [row]))

    def test_goal_total_remains_goal_total(self):
        row, issue = parse("Gole Powyżej/Poniżej", "Powyżej 2,5")
        self.assertIsNone(issue)
        self.assertEqual(row["FAMILY"], "GOALS_OU")

    def test_saved_replay_repairs_all_28_and_quarantines_only_unscoped_six(self):
        report = replay_real_prematch(
            Path("diagnostics/raw_before_dedupe_run_1787475817_15748.jsonl")
        )
        titles = {
            "1. połowa - Rzuty rożne", "Liczba Kartek 1. połowa",
            "Punkty za kartki Powyżej/Poniżej",
            "Punkty za kartki Powyżej/Poniżej - 1. połowa",
        }
        accepted = [row for row in report["odds"] if row["MARKET"] in titles]
        quarantined = [row for row in report["semantic_quarantine"]
                       if row["market"] in titles]
        self.assertEqual((len(accepted), len(quarantined)), (22, 6))
        self.assertEqual({row["FAMILY"] for row in accepted}, {"EVENT_TOTAL"})
        self.assertEqual({row["family"] for row in quarantined}, {"EVENT_TOTAL"})
        self.assertEqual({row["period"] for row in quarantined}, {"UNKNOWN"})
        self.assertEqual(report["production_accounting"]["UNACCOUNTED_SOURCE_RECORD_COUNT"], 0)


if __name__ == "__main__":
    unittest.main()
