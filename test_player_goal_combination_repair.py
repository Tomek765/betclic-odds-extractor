"""Multi-player scorer contracts preserve connective, scope, line and names."""
import unittest
from pathlib import Path

from parser import parse_market_record
from replay import replay_real_prematch


def parse(title: str, selection: str):
    return parse_market_record(
        category="Strzelcy", market_title=title, raw_selection=selection,
        odds_str="3.10", raw_text=f"{selection} 3.10", section_title="",
        home_team="Elche", away_team="Barcelona", container_id="bounded-scorer",
        main_tab="Strzelcy", market_instance_id="tab:Strzelcy|row#0",
        raw_record_id="real:1", source_raw_record_ids=["real:1"],
    )


class PlayerGoalCombinationRepair(unittest.TestCase):
    def test_any_two_scorers_preserves_or_and_both_names(self):
        row, issue = parse("Którykolwiek zawodnik strzeli gola", "L. Yamal / Raphinha")
        self.assertIsNone(issue)
        self.assertEqual((row["FAMILY"], row["SELECTION"], row["PARTICIPANT"],
                          row["PARTICIPANTS"], row["SCORER_SCOPE"], row["SETTLEMENT"]),
                         ("PLAYER_COMBINATION", "ANY_PLAYER_SCORES", "",
                          ["L. Yamal", "Raphinha"], "ANYTIME", "WIN_LOSE"))

    def test_any_three_second_half_does_not_turn_three_players_into_three_goals(self):
        row, issue = parse("Którykolwiek zawodnik strzeli gola (3 pl) - 2. połowa",
                           "L. Yamal / K.Adeyemi / Raphinha")
        self.assertIsNone(issue)
        self.assertEqual((row["FAMILY"], row["SELECTION"], len(row["PARTICIPANTS"]),
                          row["PERIOD"], row["SCORER_SCOPE"]),
                         ("PLAYER_COMBINATION", "ANY_PLAYER_SCORES", 3,
                          "2ND_HALF", "ANYTIME"))

    def test_explicit_two_plus_goal_scope_is_preserved(self):
        row, issue = parse("Którykolwiek z graczy strzeli 2 gole lub więcej",
                           "L. Yamal / Raphinha")
        self.assertIsNone(issue)
        self.assertEqual((row["SELECTION"], row["SCORER_SCOPE"], row["PARTICIPANTS"]),
                         ("ANY_PLAYER_SCORES_TWO_PLUS", "TWO_OR_MORE_GOALS",
                          ["L. Yamal", "Raphinha"]))

    def test_first_goal_and_both_halves_are_distinct_scopes(self):
        first, issue = parse("Jeden z graczy strzeli pierwszego gola", "Raphinha / L. Yamal")
        self.assertIsNone(issue)
        both, issue = parse("Jeden z graczy strzeli w obu połowach", "L. Yamal / Raphinha")
        self.assertIsNone(issue)
        self.assertEqual((first["SELECTION"], first["SCORER_SCOPE"]),
                         ("ANY_PLAYER_FIRST_GOAL", "FIRST_GOAL"))
        self.assertEqual((both["SELECTION"], both["SCORER_SCOPE"], both["PERIOD"]),
                         ("ANY_PLAYER_SCORES_BOTH_HALVES", "SCORES_BOTH_HALVES", "FULL_TIME"))

    def test_all_supersub_pair_splits_ampersand(self):
        row, issue = parse("Obaj gracze lub ich zmiennicy strzelą gola",
                           "L. Yamal & Raphinha")
        self.assertIsNone(issue)
        self.assertEqual((row["SELECTION"], row["PARTICIPANT"], row["PARTICIPANTS"],
                          row["SCORER_SCOPE"]),
                         ("ALL_PLAYERS_OR_SUBSTITUTES_SCORE", "",
                          ["L. Yamal", "Raphinha"], "ANYTIME_SUPERSUB"))

    def test_combined_goal_threshold_keeps_line_and_all_three_names(self):
        row, issue = parse("3 graczy strzeli pow. 2,5 gole",
                           "L. Yamal & A. Gordon & Raphinha")
        self.assertIsNone(issue)
        self.assertEqual((row["FAMILY"], row["SELECTION"], row["LINE"],
                          row["PARTICIPANTS"], row["SCORER_SCOPE"]),
                         ("PLAYER_COMBINATION", "SELECTED_PLAYERS_COMBINED_GOALS_OVER",
                          "2.5", ["L. Yamal", "A. Gordon", "Raphinha"], ""))

    def test_wrong_separator_or_participant_count_does_not_enter_exact_contract(self):
        row, issue = parse("3 graczy strzeli pow. 2,5 gole", "L. Yamal / Raphinha")
        self.assertIsNone(issue)
        self.assertNotEqual(row["FAMILY"], "PLAYER_COMBINATION")

    def test_single_scorer_market_remains_goal_scorer(self):
        row, issue = parse("Strzelec", "Raphinha")
        self.assertIsNone(issue)
        self.assertEqual(row["FAMILY"], "GOALSCORER")

    def test_saved_replay_repairs_all_94_multi_player_rows(self):
        report = replay_real_prematch(
            Path("diagnostics/raw_before_dedupe_run_1787475817_15748.jsonl")
        )
        modes = {
            "ANY_PLAYER_SCORES", "ANY_PLAYER_OR_SUBSTITUTE_SCORES",
            "ANY_PLAYER_SCORES_TWO_PLUS", "ANY_PLAYER_SCORES_THREE_PLUS",
            "ANY_PLAYER_FIRST_GOAL", "ANY_PLAYER_SCORES_BOTH_HALVES",
            "ALL_PLAYERS_OR_SUBSTITUTES_SCORE",
            "SELECTED_PLAYERS_COMBINED_GOALS_OVER",
        }
        rows = [row for row in report["odds"] if row["SELECTION"] in modes]
        self.assertEqual(len(rows), 94)
        self.assertEqual({row["FAMILY"] for row in rows}, {"PLAYER_COMBINATION"})
        self.assertTrue(all(len(row["PARTICIPANTS"]) in {2, 3} for row in rows))
        threshold_rows = [row for row in rows if row["SELECTION"] ==
                          "SELECTED_PLAYERS_COMBINED_GOALS_OVER"]
        self.assertEqual(len(threshold_rows), 27)
        self.assertEqual({row["LINE"] for row in threshold_rows}, {"1.5", "2.5", "3.5"})


if __name__ == "__main__":
    unittest.main()
