"""Exact match compounds must not collapse into their broad component family."""
import unittest
from pathlib import Path

from parser import parse_market_record
from replay import replay_real_prematch


def parse(title: str, selection: str, *, period_hint: str = ""):
    return parse_market_record(
        category="Gole", market_title=title, raw_selection=selection,
        odds_str="2.10", raw_text=f"{selection} 2.10", section_title="Gole - popularne",
        home_team="Elche", away_team="Barcelona", container_id="exact-compound",
        period_hint=period_hint, main_tab="Gole",
        market_instance_id="tab:Gole|row#0", raw_record_id="real:1",
        source_raw_record_ids=["real:1"],
    )


class MatchCompoundFalseAcceptRepair(unittest.TestCase):
    def assert_compound(self, row, selection: str, line: str = ""):
        self.assertEqual(
            (row["FAMILY"], row["SELECTION"], row["LINE"], row["OWNER"],
             row["PARTICIPANT"], row["PARTICIPANTS"], row["SETTLEMENT"]),
            ("COMPOUND_LOGIC", selection, line, "", "", [], "WIN_LOSE"),
        )

    def test_both_halves_total_is_binary_compound_not_goals_total(self):
        row, issue = parse("Obie połowy powyżej 1,5 goli", "Tak")
        self.assertIsNone(issue)
        self.assert_compound(row, "BOTH_HALVES_OVER_YES", "1.5")
        self.assertEqual(row["PERIOD"], "FULL_TIME")

    def test_ordered_half_btts_and_two_plus_keep_every_predicate(self):
        ordered, issue = parse("Oba zespoły strzelą w 1. i 2. połowie", "Tak / Nie")
        self.assertIsNone(issue)
        two, issue = parse("Obie drużyny strzelą po 2+", "Nie")
        self.assertIsNone(issue)
        self.assert_compound(ordered, "BTTS_H1_YES_H2_NO")
        self.assert_compound(two, "BOTH_TEAMS_AT_LEAST_TWO_NO", "2")

    def test_double_chance_compounds_keep_side_condition_and_line(self):
        btts, issue = parse("Podwójna szansa & oba zespoły strzelą",
                            "Elche / Remis & Tak")
        self.assertIsNone(issue)
        total, issue = parse("Podwójna szansa & powyżej/poniżej",
                             "Elche / Remis & Powyżej 2,5")
        self.assertIsNone(issue)
        first_half, issue = parse(
            "Podwójna szansa, obie drużyny zdobywają gole - 1. połowa",
            "Barcelona / Remis & Nie",
        )
        self.assertIsNone(issue)
        self.assert_compound(btts, "DC_HOME_DRAW_AND_BTTS_YES")
        self.assert_compound(total, "DC_HOME_DRAW_AND_OVER", "2.5")
        self.assert_compound(first_half, "DC_AWAY_DRAW_AND_BTTS_NO")
        self.assertEqual(first_half["PERIOD"], "1ST_HALF")

    def test_result_occurs_half_or_full_is_not_double_chance(self):
        row, issue = parse("Podwójna szansa (1.połowa lub mecz)", "Barcelona")
        self.assertIsNone(issue)
        self.assert_compound(row, "AWAY_RESULT_OCCURS_1H_OR_FT")
        self.assertEqual(row["PERIOD"], "FULL_TIME")

    def test_result_and_first_goal_preserves_both_ordered_sides(self):
        row, issue = parse("Wynik i kto zdobędzie 1. bramkę",
                           "Elche / Barcelona strzeli pierwszy")
        self.assertIsNone(issue)
        self.assert_compound(row, "HOME_RESULT_AND_AWAY_FIRST")

    def test_btts_total_compounds_recover_explicit_2_5_line(self):
        disjunction, issue = parse(
            "Oba zespoły strzelą gola lub Powyżej 2,5 gola w meczu", "Nie",
        )
        self.assertIsNone(issue)
        conjunction, issue = parse(
            "Oba zespoły strzelą gola / Liczba bramek", "Nie i poniżej 2,5",
        )
        self.assertIsNone(issue)
        self.assert_compound(disjunction, "BTTS_OR_OVER_NO", "2.5")
        self.assert_compound(conjunction, "BTTS_NO_AND_UNDER", "2.5")

    def test_win_to_nil_is_not_clean_sheet(self):
        row, issue = parse("Zwycięstwo do zera", "Tak", period_hint="Gospodarze")
        self.assertIsNone(issue)
        self.assertEqual(
            (row["FAMILY"], row["SELECTION"], row["OWNER"], row["PERIOD"],
             row["SETTLEMENT"]),
            ("TEAM_WIN_TO_NIL", "YES", "Elche", "FULL_TIME", "WIN_LOSE"),
        )

    def test_120_minute_result_never_uses_full_time_scope(self):
        row, issue = parse("1x2 Strzały (120 min)", "Elche")
        self.assertIsNone(issue)
        self.assertEqual(
            (row["FAMILY"], row["SELECTION"], row["PERIOD"], row["PERIOD_SOURCE"],
             row["MARKET_SCOPE"], row["SETTLEMENT"]),
            ("1X2", "HOME", "MATCH_INCLUDING_EXTRA_TIME", "MARKET_TITLE", "MATCH_INCLUDING_EXTRA_TIME", "WIN_LOSE"),
        )

    def test_saved_replay_repairs_all_39_audited_rows_losslessly(self):
        report = replay_real_prematch(
            Path("diagnostics/raw_before_dedupe_run_1787475817_15748.jsonl")
        )
        rows = report["odds"]
        by_source = {
            source: row for row in rows for source in row["source_raw_record_ids"]
        }
        compound_ids = (
            set(range(1135, 1141)) | {1003, 1004} | set(range(1122, 1126))
            | set(range(260, 263)) | set(range(281, 290)) | set(range(303, 306))
            | {947, 948} | set(range(995, 999))
        )
        compound_sources = {f"run_1787475817_15748:{value}" for value in compound_ids}
        self.assertEqual({by_source[source]["FAMILY"] for source in compound_sources},
                         {"COMPOUND_LOGIC"})
        self.assertTrue(all(by_source[source]["SETTLEMENT"] == "WIN_LOSE"
                            for source in compound_sources))
        line_ids = {284, 285, 286, 947, 948, 995, 996, 997, 998, 1003, 1004}
        self.assertTrue(all(by_source[f"run_1787475817_15748:{value}"]["LINE"]
                            for value in line_ids))
        win_ids = {f"run_1787475817_15748:{value}" for value in range(299, 303)}
        self.assertEqual({by_source[source]["FAMILY"] for source in win_ids},
                         {"TEAM_WIN_TO_NIL"})
        minute_ids = {f"run_1787475817_15748:{value}" for value in (1366, 1367)}
        self.assertEqual({by_source[source]["PERIOD"] for source in minute_ids}, {"MATCH_INCLUDING_EXTRA_TIME"})
        accounting = report["production_accounting"]
        self.assertEqual(accounting["SEMANTIC_ACCEPTED_COUNT"]
                         + accounting["SEMANTIC_QUARANTINED_COUNT"], 1394)
        self.assertEqual(accounting["UNACCOUNTED_SOURCE_RECORD_COUNT"], 0)
        self.assertTrue(accounting["ALL_SOURCE_IDS_PRESERVED"])


if __name__ == "__main__":
    unittest.main()
