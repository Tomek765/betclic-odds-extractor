"""Grouped scorer columns are predicates, never decorative labels."""
import unittest
from pathlib import Path

from parser import parse_market_record
from replay import replay_real_prematch


def parse(title: str, player: str, column: str = ""):
    return parse_market_record(
        category="Strzelcy", market_title=title, raw_selection=player,
        odds_str="3.40", raw_text=f"{player} 3.40", section_title="Strzelec",
        home_team="Elche", away_team="Barcelona", container_id="grouped-scorer",
        period_hint=column, main_tab="Strzelcy",
        market_instance_id=f"tab:Strzelcy|column:{column.replace(' ', '.')}|row#0",
        raw_record_id="real:1", source_raw_record_ids=["real:1"],
    )


class ScorerColumnSemanticsRepair(unittest.TestCase):
    def test_scorer_and_team_result_column_is_preserved(self):
        row, issue = parse("Strzelcy", "Raphinha", "i jego zespół wygra")
        self.assertIsNone(issue)
        self.assertEqual((row["FAMILY"], row["PARTICIPANT"], row["SELECTION"],
                          row["SCORER_SCOPE"], row["OWNER"], row["SETTLEMENT"]),
                         ("GOALSCORER", "Raphinha", "SCORER_AND_TEAM_WIN",
                          "ANYTIME", "", "WIN_LOSE"))

    def test_supersub_scorer_and_team_result_is_distinct(self):
        row, issue = parse("Strzelec gola lub jego zmiennik", "Raphinha",
                           "jego drużyna zremisuje")
        self.assertIsNone(issue)
        self.assertEqual((row["PARTICIPANT"], row["SELECTION"], row["SCORER_SCOPE"]),
                         ("Raphinha", "SCORER_OR_SUBSTITUTE_AND_TEAM_DRAW",
                          "ANYTIME_SUPERSUB"))

    def test_scorer_and_substitute_goal_threshold_columns_are_not_anytime(self):
        two, issue = parse("Strzelec i jego zmiennik", "Raphinha", "2 lub więcej")
        self.assertIsNone(issue)
        three, issue = parse("Strzelec i jego zmiennik", "Raphinha", "3 lub więcej")
        self.assertIsNone(issue)
        self.assertEqual((two["SELECTION"], two["SCORER_SCOPE"]),
                         ("SCORER_AND_SUBSTITUTE_TWO_PLUS", "TWO_OR_MORE_GOALS"))
        self.assertEqual((three["SELECTION"], three["SCORER_SCOPE"]),
                         ("SCORER_AND_SUBSTITUTE_THREE_PLUS", "THREE_OR_MORE_GOALS"))

    def test_four_plus_and_both_halves_columns_have_exact_scope(self):
        four, issue = parse("Strzelec", "Raphinha", "4 lub więcej goli")
        self.assertIsNone(issue)
        both, issue = parse("Strzelec", "Raphinha", "obu połowach")
        self.assertIsNone(issue)
        self.assertEqual(four["SCORER_SCOPE"], "FOUR_OR_MORE_GOALS")
        self.assertEqual(both["SCORER_SCOPE"], "SCORES_BOTH_HALVES")

    def test_outscore_opponent_is_player_prop_with_explicit_90_minutes(self):
        row, issue = parse("Zawodnik strzeli więcej goli niż drużyna przeciwna (90 min)",
                           "Raphinha")
        self.assertIsNone(issue)
        self.assertEqual((row["FAMILY"], row["PARTICIPANT"], row["SELECTION"],
                          row["SCORER_SCOPE"], row["PERIOD"], row["PERIOD_SOURCE"],
                          row["SETTLEMENT"]),
                         ("PLAYER_PROP", "Raphinha", "OUTSCORES_OPPONENT", "",
                          "FULL_TIME", "MARKET_TITLE", "WIN_LOSE"))

    def test_saved_replay_repairs_every_audited_column(self):
        report = replay_real_prematch(
            Path("diagnostics/raw_before_dedupe_run_1787475817_15748.jsonl")
        )
        rows = report["odds"]
        result_modes = {"SCORER_AND_TEAM_WIN", "SCORER_AND_TEAM_DRAW",
                        "SCORER_AND_TEAM_LOSS",
                        "SCORER_OR_SUBSTITUTE_AND_TEAM_WIN",
                        "SCORER_OR_SUBSTITUTE_AND_TEAM_DRAW",
                        "SCORER_OR_SUBSTITUTE_AND_TEAM_LOSS"}
        self.assertEqual(sum(row["SELECTION"] in result_modes for row in rows), 36)
        self.assertEqual(sum(row["SELECTION"].startswith("SCORER_AND_SUBSTITUTE_")
                             for row in rows), 12)
        self.assertEqual(sum(row["SCORER_SCOPE"] == "FOUR_OR_MORE_GOALS" for row in rows), 6)
        self.assertEqual(sum(row["SCORER_SCOPE"] in {
            "SCORES_BOTH_HALVES", "ALL_SCORE_BOTH_HALVES",
        } for row in rows), 21)
        outscore = [row for row in rows if row["SELECTION"] == "OUTSCORES_OPPONENT"]
        self.assertEqual(len(outscore), 6)
        self.assertEqual({row["FAMILY"] for row in outscore}, {"PLAYER_PROP"})


if __name__ == "__main__":
    unittest.main()
