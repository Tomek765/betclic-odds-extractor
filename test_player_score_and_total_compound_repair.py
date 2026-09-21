"""Regression contract for half-scoped player-score AND goal-total offers."""
import unittest
from collections import Counter
from pathlib import Path

from parser import parse_market_record
from replay import replay_real_prematch


def parse(title: str, selection: str = "Anthony Gordon"):
    return parse_market_record(
        category="Strzelcy", market_title=title, raw_selection=selection,
        odds_str="5.25", raw_text=f"{selection} 5.25", section_title="Barcelona",
        home_team="Elche", away_team="Barcelona", container_id="bounded-card",
        main_tab="Strzelcy", market_instance_id="tab:Strzelcy|row#5",
        raw_record_id="real:834", source_raw_record_ids=["real:834"],
    )


class PlayerScoreAndTotalCompoundRepair(unittest.TestCase):
    def test_first_half_exact_template_preserves_both_predicates_and_player(self):
        row, issue = parse("Zawodnik strzeli i powyżej 1,5 goli - 1. połowa")
        self.assertIsNone(issue)
        self.assertEqual(
            (row["FAMILY"], row["PARTICIPANT"], row["PARTICIPANTS"],
             row["SELECTION"], row["LINE"], row["PERIOD"], row["SCORER_SCOPE"],
             row["SETTLEMENT"], row["OWNER"]),
            ("PLAYER_PROP", "Anthony Gordon", ["Anthony Gordon"],
             "SCORE_AND_TOTAL_OVER", "1.5", "1ST_HALF", "ANYTIME",
             "WIN_LOSE", "Barcelona"),
        )

    def test_second_half_exact_template_is_equally_bounded(self):
        row, issue = parse("Zawodnik strzeli i powyżej 1,5 goli - 2. połowa")
        self.assertIsNone(issue)
        self.assertEqual((row["FAMILY"], row["PERIOD"], row["LINE"], row["SELECTION"]),
                         ("PLAYER_PROP", "2ND_HALF", "1.5", "SCORE_AND_TOTAL_OVER"))

    def test_plain_half_goal_total_remains_a_goal_total(self):
        row, issue = parse("Gole 1. połowa", "Powyżej 1,5")
        self.assertIsNone(issue)
        self.assertEqual((row["FAMILY"], row["SELECTION"], row["LINE"], row["PARTICIPANT"]),
                         ("GOALS_OU", "OVER", "1.5", ""))

    def test_saved_replay_repairs_all_twelve_without_accounting_delta(self):
        report = replay_real_prematch(
            Path("diagnostics/raw_before_dedupe_run_1787475817_15748.jsonl")
        )
        rows = [row for row in report["odds"] if row["MARKET"].startswith(
            "Zawodnik strzeli i powyżej 1,5 goli"
        )]
        self.assertEqual(len(rows), 12)
        self.assertEqual(Counter(row["FAMILY"] for row in rows), {"PLAYER_PROP": 12})
        self.assertEqual({row["SELECTION"] for row in rows}, {"SCORE_AND_TOTAL_OVER"})
        self.assertEqual({row["LINE"] for row in rows}, {"1.5"})
        self.assertTrue(all(row["PARTICIPANT"] for row in rows))
        accounting = report["production_accounting"]
        self.assertEqual(accounting["SEMANTIC_ACCEPTED_COUNT"] +
                         accounting["SEMANTIC_QUARANTINED_COUNT"], 1394)
        self.assertEqual(accounting["UNACCOUNTED_SOURCE_RECORD_COUNT"], 0)


if __name__ == "__main__":
    unittest.main()
