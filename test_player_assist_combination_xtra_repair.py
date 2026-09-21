"""Real regressions for pure-assist ANY combinations and Xtra rows."""
import unittest

from core import partition_semantic_records, semantic_quarantine_ledger
from parser import parse_market_record


ANY_TWO = "Którykolwiek zawodnik zaliczy asystę"
ANY_THREE = ANY_TWO + " - 3 zawodników"
XTRA = "Zawodnik zaliczy asystę - Xtra Wygrana"

COMBINATION_ROWS = (
    ("run_1787475817_15748:734", ANY_TWO, "Raphinha / L. Yamal", "1.69", "ANY_ASSIST"),
    ("run_1787475817_15748:735", ANY_TWO, "A. Gordon / L. Yamal", "1.81", "ANY_ASSIST"),
    ("run_1787475817_15748:736", ANY_TWO, "A. Gordon / Raphinha", "1.82", "ANY_ASSIST"),
    ("run_1787475817_15748:737", ANY_TWO, "K.Adeyemi / L. Yamal", "1.84", "ANY_ASSIST"),
    ("run_1787475817_15748:738", ANY_TWO, "L. Yamal / F. Lopez", "1.84", "ANY_ASSIST"),
    ("run_1787475817_15748:739", ANY_TWO, "Raphinha / K.Adeyemi", "1.85", "ANY_ASSIST"),
    ("run_1787475817_15748:740", ANY_THREE, "A. Gordon / Raphinha / L. Yamal", "1.38", "ANY_ASSIST_THREE_PLAYERS"),
    ("run_1787475817_15748:741", ANY_THREE, "Raphinha / K.Adeyemi / L. Yamal", "1.39", "ANY_ASSIST_THREE_PLAYERS"),
    ("run_1787475817_15748:742", ANY_THREE, "Raphinha / L. Yamal / F. Lopez", "1.39", "ANY_ASSIST_THREE_PLAYERS"),
)

XTRA_ROWS = (
    ("run_1787475817_15748:1543", "Elche", "Grady Diangana", "6.60"),
    ("run_1787475817_15748:1544", "Elche", "Josan Ferrández", "6.60"),
    ("run_1787475817_15748:1545", "Elche", "German Valera", "7.00"),
    ("run_1787475817_15748:1546", "Barcelona", "Lamine Yamal", "2.47"),
    ("run_1787475817_15748:1547", "Barcelona", "Raphinha", "2.52"),
    ("run_1787475817_15748:1548", "Barcelona", "Anthony Gordon", "3.05"),
)


def parse_row(source_id, title, selection, odds, *, section="Strzelec"):
    return parse_market_record(
        category="Statystyki", market_title=title, raw_selection=selection,
        odds_str=odds, raw_text=f"{selection} {odds}", section_title=section,
        participant_hint=None, line_hint="", period_hint="", ancestor_title=section,
        main_tab="Statystyki", home_team="Elche", away_team="Barcelona",
        container_id="bounded-pure-assist-row",
        market_instance_id=f"tab:Statystyki|pureAssist|{source_id}",
        raw_record_id=source_id, source_raw_record_ids=[source_id],
    )


class PlayerAssistCombinationXtraRepair(unittest.TestCase):
    def assert_period_quarantine(self, row):
        accepted, quarantined = partition_semantic_records([row])
        self.assertEqual((accepted, quarantined), ([], [row]))
        self.assertEqual(
            semantic_quarantine_ledger(quarantined)[0]["reason"],
            "UNCONFIRMED_XTRA_PAYOUT_CONTRACT",
        )

    def test_any_two_and_any_three_preserve_every_row_local_participant(self):
        for source_id, title, selection, odds, condition in COMBINATION_ROWS:
            with self.subTest(source_id=source_id):
                row, issue = parse_row(source_id, title, selection, odds)
                self.assertIsNone(issue)
                self.assertEqual(
                    (row["FAMILY"], row["PARTICIPANT"], row["PARTICIPANTS"],
                     row["OWNER"], row["SELECTION"], row["LINE"], row["PERIOD"],
                     row["SETTLEMENT"], row["SCORER_SCOPE"], row["ODDS"]),
                    ("PLAYER_COMBINATION", "", selection.split(" / "), "", condition,
                     "", "FULL_TIME", "WIN_LOSE", "", odds),
                )
                self.assertEqual(partition_semantic_records([row]), ([row], []))

    def test_xtra_rows_keep_player_team_and_unknown_payout_contract(self):
        for source_id, team, player, odds in XTRA_ROWS:
            with self.subTest(source_id=source_id):
                row, issue = parse_row(source_id, XTRA, player, odds, section=team)
                self.assertIsNone(issue)
                self.assertEqual(
                    (row["FAMILY"], row["PARTICIPANT"], row["PARTICIPANTS"],
                     row["OWNER"], row["SELECTION"], row["LINE"], row["PERIOD"],
                     row["SETTLEMENT"], row["SCORER_SCOPE"], row["ODDS"]),
                    ("PLAYER_PROP_XTRA", player, [player], team, "ASSIST_XTRA", "",
                     "UNKNOWN", "UNKNOWN", "", odds),
                )
                self.assert_period_quarantine(row)

    def test_unknown_similar_titles_do_not_enter_exact_contracts(self):
        combo, _ = parse_row("negative:1", ANY_TWO + " specjalny", "A / B", "2.00")
        xtra, _ = parse_row("negative:2", XTRA + " 2", "Raphinha", "2.00", section="Barcelona")
        self.assertNotEqual(combo["FAMILY"], "PLAYER_COMBINATION")
        self.assertNotEqual(xtra["FAMILY"], "PLAYER_PROP_XTRA")


if __name__ == "__main__":
    unittest.main()
