"""Real regression for exact player penalty-conversion rows."""
import unittest

from core import partition_semantic_records
from parser import classify_family, parse_market_record


TITLE = "Zawodnik wykorzysta rzut karny."
REAL_ROWS = (
    ("run_1787475817_15748:866", "Elche", "Fer Nino", "9.00"),
    ("run_1787475817_15748:867", "Elche", "Ezequiel Ponce", "10"),
    ("run_1787475817_15748:868", "Barcelona", "Raphinha", "3.30"),
    ("run_1787475817_15748:869", "Barcelona", "Lamine Yamal", "3.40"),
    ("run_1787475817_15748:870", "Barcelona", "Fermin Lopez", "4.50"),
)


def parse_row(raw):
    source_id, team, player, odds = raw
    return parse_market_record(
        category="Strzelcy", market_title=TITLE, raw_selection=player,
        odds_str=odds, raw_text=f"{player} {odds}", section_title=team,
        participant_hint=None, line_hint="", period_hint="", ancestor_title="Strzelec",
        main_tab="Strzelcy", home_team="Elche", away_team="Barcelona",
        container_id="bounded-player-penalty-row",
        market_instance_id=f"tab:Strzelcy|single[playerPenalty]|{source_id}",
        raw_record_id=source_id, source_raw_record_ids=[source_id],
    )


class PlayerPenaltyConversionRepair(unittest.TestCase):
    def test_all_five_rows_preserve_player_team_and_odds(self):
        for raw in REAL_ROWS:
            source_id, team, player, odds = raw
            with self.subTest(source_id=source_id):
                row, issue = parse_row(raw)
                self.assertIsNone(issue)
                self.assertEqual(
                    (row["FAMILY"], row["PARTICIPANT"], row["PARTICIPANTS"],
                     row["OWNER"], row["SELECTION"], row["LINE"], row["PERIOD"],
                     row["PERIOD_SOURCE"], row["PERIOD_CONFIDENCE"],
                     row["SETTLEMENT"], row["SCORER_SCOPE"],
                     row["COLUMN_SEMANTICS_STATUS"], row["ODDS"]),
                    ("GOALSCORER", player, [player], team, player, "", "FULL_TIME",
                     "CANONICAL_MARKET", "MEDIUM", "WIN_LOSE", "ANYTIME", "PROVEN",
                     odds),
                )
                accepted, quarantined = partition_semantic_records([row])
                self.assertEqual((accepted, quarantined), ([row], []))

    def test_adjacent_rows_do_not_cross_link(self):
        parsed = [parse_row(raw)[0] for raw in REAL_ROWS]
        self.assertEqual([row["PARTICIPANT"] for row in parsed], [raw[2] for raw in REAL_ROWS])
        self.assertEqual([row["OWNER"] for row in parsed], [raw[1] for raw in REAL_ROWS])
        self.assertEqual([row["ODDS"] for row in parsed], [raw[3] for raw in REAL_ROWS])

    def test_match_penalty_and_assist_markets_are_firewalled(self):
        cases = (
            ("Gol z rzutu karnego", "Tak", "PENALTY_GOAL"),
            ("Gol z rzutu karnego - 1. połowa", "Tak", "PENALTY_GOAL"),
            ("Oba zespoły strzelą z rzutu karnego", "Tak", "BTTS"),
        )
        for title, selection, expected in cases:
            with self.subTest(title=title):
                self.assertEqual(
                    classify_family(title, selection, "", "Elche", "Barcelona")[0],
                    expected,
                )
        self.assertNotEqual(
            classify_family("Zawodnik zaliczy asystę", "Raphinha", "", "Elche", "Barcelona")[0],
            "GOALSCORER",
        )


if __name__ == "__main__":
    unittest.main()
