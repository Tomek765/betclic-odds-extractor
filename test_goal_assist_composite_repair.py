"""Regression firewall for exact goal/assist composite contracts."""
import unittest

from core import partition_semantic_records, semantic_quarantine_ledger
from parser import parse_market_record


BASE_OR = "Zawodnik strzeli gola lub zaliczy asystę"
SUPERSUB_OR = BASE_OR + " + jego zmiennik"
ANY_OR = "Którykolwiek zawodnik strzeli gola lub zaliczy asystę"
ALL_OR = "Obaj gracze strzelą gola lub zaliczą asystę"
BASE_AND = "Zawodnik strzeli gola i zaliczy asystę"
SUPERSUB_AND = "Zawodnik lub jego zmiennik strzeli gola i zaliczy asystę"
XTRA_OR = BASE_OR + " - Xtra Wygrana"


def parse_case(source_id, title, player, odds, *, hint="", team="", tab="Strzelcy"):
    return parse_market_record(
        category=tab, market_title=title, raw_selection=player, odds_str=odds,
        raw_text=f"{player} {odds}", section_title=team,
        participant_hint=None, line_hint="", period_hint=hint,
        ancestor_title="Strzelec", main_tab=tab,
        home_team="Elche", away_team="Barcelona",
        container_id="bounded-goal-assist-row",
        market_instance_id=f"tab:{tab}|goalAssist|column:{hint}|{source_id}",
        raw_record_id=source_id, source_raw_record_ids=[source_id],
    )


class GoalAssistCompositeRepair(unittest.TestCase):
    def assert_regulatory_disposition(self, row):
        if row["FAMILY"] != "PLAYER_PROP_XTRA":
            self.assertEqual(partition_semantic_records([row]), ([row], []))
            return
        accepted, quarantined = partition_semantic_records([row])
        self.assertEqual((accepted, quarantined), ([], [row]))
        self.assertEqual(
            semantic_quarantine_ledger(quarantined)[0]["reason"],
            "UNCONFIRMED_XTRA_PAYOUT_CONTRACT",
        )

    def test_ordinary_threshold_cells_keep_metric_and_regulatory_period(self):
        cases = (
            ("run_1787475817_15748:66", "Umaru Konare", "2.90", "1 +", "0.5"),
            ("run_1787475817_15748:67", "Umaru Konare", "12", "2 +", "1.5"),
            ("run_1787475817_15748:68", "Umaru Konare", "60", "3 +", "2.5"),
            ("run_1787475817_15748:69", "Fer Nino", "3.20", "1 +", "0.5"),
            ("run_1787475817_15748:70", "Fer Nino", "15", "2 +", "1.5"),
            ("run_1787475817_15748:71", "Fer Nino", "80", "3 +", "2.5"),
        )
        for source_id, player, odds, hint, line in cases:
            with self.subTest(source_id=source_id):
                row, issue = parse_case(source_id, BASE_OR, player, odds, hint=hint, tab="Top")
                self.assertIsNone(issue)
                self.assertEqual(
                    (row["FAMILY"], row["PARTICIPANT"], row["PARTICIPANTS"],
                     row["SELECTION"], row["LINE"], row["PERIOD"],
                     row["SETTLEMENT"], row["SCORER_SCOPE"],
                     row["COLUMN_SEMANTICS_STATUS"], row["ODDS"]),
                    ("PLAYER_PROP", player, [player], "OVER", line, "FULL_TIME",
                     "WIN_LOSE", "", "NOT_APPLICABLE", odds),
                )
                self.assert_regulatory_disposition(row)

    def test_result_columns_keep_goal_or_assist_compound_predicate(self):
        cases = (
            ("run_1787475817_15748:491", "Umaru Konare", "9.75", "i jego zespół wygra", "GOAL_OR_ASSIST_AND_TEAM_WIN"),
            ("run_1787475817_15748:492", "Umaru Konare", "13.25", "i jego zespół zremisuje", "GOAL_OR_ASSIST_AND_TEAM_DRAW"),
            ("run_1787475817_15748:493", "Umaru Konare", "6.25", "i zespół przegra", "GOAL_OR_ASSIST_AND_TEAM_LOSS"),
            ("run_1787475817_15748:494", "Fer Nino", "10.75", "i jego zespół wygra", "GOAL_OR_ASSIST_AND_TEAM_WIN"),
            ("run_1787475817_15748:495", "Fer Nino", "14.75", "i jego zespół zremisuje", "GOAL_OR_ASSIST_AND_TEAM_DRAW"),
            ("run_1787475817_15748:496", "Fer Nino", "6.90", "i zespół przegra", "GOAL_OR_ASSIST_AND_TEAM_LOSS"),
        )
        for source_id, player, odds, hint, condition in cases:
            row, _ = parse_case(source_id, BASE_OR, player, odds, hint=hint)
            self.assertEqual(
                (row["FAMILY"], row["PARTICIPANT"], row["SELECTION"], row["LINE"],
                 row["PERIOD"], row["SETTLEMENT"], row["ODDS"]),
                ("PLAYER_PROP", player, condition, "", "FULL_TIME", "WIN_LOSE", odds),
            )
            self.assert_regulatory_disposition(row)

    def test_supersub_thresholds_preserve_variant_and_count_metric(self):
        cases = (
            ("run_1787475817_15748:42", "Umaru Konare", "2.65", "1x lub więcej", "0.5"),
            ("run_1787475817_15748:43", "Umaru Konare", "10", "2x lub więcej", "1.5"),
            ("run_1787475817_15748:44", "Umaru Konare", "40", "3x lub więcej", "2.5"),
            ("run_1787475817_15748:45", "Fer Nino", "2.95", "1x lub więcej", "0.5"),
            ("run_1787475817_15748:46", "Fer Nino", "12", "2x lub więcej", "1.5"),
            ("run_1787475817_15748:47", "Fer Nino", "60", "3x lub więcej", "2.5"),
        )
        for source_id, player, odds, hint, line in cases:
            row, _ = parse_case(source_id, SUPERSUB_OR, player, odds, hint=hint, tab="Top")
            self.assertEqual(
                (row["FAMILY"], row["PARTICIPANT"], row["SELECTION"], row["LINE"],
                 row["PERIOD"], row["SETTLEMENT"], row["ODDS"]),
                ("PLAYER_PROP", player, "OVER", line, "FULL_TIME", "WIN_LOSE", odds),
            )
            self.assert_regulatory_disposition(row)

    def test_any_and_all_combinations_split_only_the_proven_connective(self):
        any_cases = (
            ("run_1787475817_15748:103", "L. Yamal / Raphinha", "1.09"),
            ("run_1787475817_15748:104", "A. Gordon / Raphinha", "1.13"),
        )
        all_cases = (
            ("run_1787475817_15748:596", "L. Yamal & Raphinha", "2.08"),
            ("run_1787475817_15748:597", "A. Gordon & Raphinha", "2.40"),
        )
        for source_id, selection, odds in any_cases:
            row, _ = parse_case(source_id, ANY_OR, selection, odds, tab="Top")
            self.assertEqual(
                (row["FAMILY"], row["PARTICIPANT"], row["PARTICIPANTS"],
                 row["SELECTION"], row["PERIOD"], row["SETTLEMENT"], row["ODDS"]),
                ("PLAYER_COMBINATION", "", selection.split(" / "),
                 "ANY_GOAL_OR_ASSIST", "FULL_TIME", "WIN_LOSE", odds),
            )
            self.assert_regulatory_disposition(row)
        for source_id, selection, odds in all_cases:
            row, _ = parse_case(source_id, ALL_OR, selection, odds)
            self.assertEqual(
                (row["FAMILY"], row["PARTICIPANT"], row["PARTICIPANTS"],
                 row["SELECTION"], row["PERIOD"], row["SETTLEMENT"], row["ODDS"]),
                ("PLAYER_COMBINATION", "", selection.split(" & "),
                 "ALL_GOAL_OR_ASSIST", "FULL_TIME", "WIN_LOSE", odds),
            )
            self.assert_regulatory_disposition(row)

    def test_and_supersub_and_xtra_variants_never_collapse_to_scorer(self):
        cases = (
            ("run_1787475817_15748:728", BASE_AND, "Fer Nino", "40", "Elche", "PLAYER_PROP", "GOAL_AND_ASSIST", "WIN_LOSE"),
            ("run_1787475817_15748:731", BASE_AND, "Raphinha", "6.60", "Barcelona", "PLAYER_PROP", "GOAL_AND_ASSIST", "WIN_LOSE"),
            ("run_1787475817_15748:395", SUPERSUB_AND, "Umaru Konare", "28", "Elche", "PLAYER_PROP", "GOAL_AND_ASSIST", "WIN_LOSE"),
            ("run_1787475817_15748:398", SUPERSUB_AND, "Raphinha", "5.60", "Barcelona", "PLAYER_PROP", "GOAL_AND_ASSIST", "WIN_LOSE"),
            ("run_1787475817_15748:60", XTRA_OR, "Umaru Konare", "2.57", "Elche", "PLAYER_PROP_XTRA", "GOAL_OR_ASSIST_XTRA", "UNKNOWN"),
            ("run_1787475817_15748:63", XTRA_OR, "Lamine Yamal", "1.32", "Barcelona", "PLAYER_PROP_XTRA", "GOAL_OR_ASSIST_XTRA", "UNKNOWN"),
        )
        for source_id, title, player, odds, team, family, selection, settlement in cases:
            row, _ = parse_case(source_id, title, player, odds, team=team,
                                tab="SuperSub" if "zmiennik" in title else "Strzelcy")
            self.assertEqual(
                (row["FAMILY"], row["PARTICIPANT"], row["PARTICIPANTS"], row["OWNER"],
                 row["SELECTION"], row["LINE"], row["PERIOD"], row["SETTLEMENT"],
                 row["SCORER_SCOPE"], row["ODDS"]),
                (family, player, [player], team, selection, "", "UNKNOWN" if family == "PLAYER_PROP_XTRA" else "FULL_TIME", settlement,
                 "", odds),
            )
            self.assert_regulatory_disposition(row)

    def test_normal_scorer_and_unknown_near_match_are_firewalled(self):
        normal, _ = parse_case("negative:1", "Strzelec gola", "Raphinha", "2.20", team="Barcelona")
        near, _ = parse_case("negative:2", BASE_OR + " (specjalny)", "Raphinha", "2.20")
        self.assertEqual(normal["FAMILY"], "GOALSCORER")
        self.assertNotEqual(near["FAMILY"], "PLAYER_PROP")
        self.assertNotEqual(near["FAMILY"], "PLAYER_PROP_XTRA")


if __name__ == "__main__":
    unittest.main()
