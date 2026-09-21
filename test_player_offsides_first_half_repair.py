"""Real Elche–Barcelona regression for first-half inline player offsides."""
import unittest

from core import partition_semantic_records
from parser import classify_family, parse_market_record


# Lossless reductions of fresh run_1787474911_3524 records :1537–:1542.
# Each player/outcome/line label and its odds button belong to the same
# div.marketBox_lineSelection.  The explicit period is retained in the market
# title; no participant, line or period defaults are supplied to the parser.
REAL_FIRST_HALF_OFFSIDES_ROWS = (
    ("run_1787474911_3524:1537", "Elche", "Ezequiel Ponce", "1.55", "#1", "#1"),
    ("run_1787474911_3524:1538", "Elche", "Fer Nino", "1.58", "#1", "#2"),
    ("run_1787474911_3524:1539", "Elche", "Umaru Konare", "2.05", "#1", "#3"),
    ("run_1787474911_3524:1540", "Barcelona", "Karim Adeyemi", "3.10", "#2", "#1"),
    ("run_1787474911_3524:1541", "Barcelona", "Raphinha", "3.70", "#2", "#2"),
    ("run_1787474911_3524:1542", "Barcelona", "Lamine Yamal", "4.00", "#2", "#3"),
)

TITLE = "Liczba spalonych zawodnika (OPTA) - 1. połowa"


def parse_real_row(raw):
    source_id, team, player, odds, card_index, row_index = raw
    selection = f"{player} Powyżej 0,5"
    instance = (
        "tab:Statystyki|sports-markets-single-market[block.marketElement#77]|"
        f"sports-split-card[{card_index}]|row{row_index}|div[marketBox_lineSelection{row_index}]"
    )
    return parse_market_record(
        category="Statystyki", market_title=TITLE, raw_selection=selection,
        odds_str=odds, raw_text=f"{selection} {odds}", section_title=team,
        participant_hint=None, line_hint="", period_hint="", ancestor_title="",
        main_tab="Statystyki", home_team="Elche", away_team="Barcelona",
        container_id="bounded-first-half-single-market-row",
        market_instance_id=instance, raw_record_id=source_id,
        source_raw_record_ids=[source_id],
    )


class PlayerOffsidesFirstHalfRepair(unittest.TestCase):
    def test_all_real_first_half_rows_have_complete_player_prop_semantics(self):
        for raw in REAL_FIRST_HALF_OFFSIDES_ROWS:
            source_id, team, player, odds, _, _ = raw
            with self.subTest(source_id=source_id):
                row, unresolved = parse_real_row(raw)
                self.assertIsNone(unresolved)
                self.assertEqual(
                    (row["FAMILY"], row["PARTICIPANT"], row["OWNER"],
                     row["SELECTION"], row["LINE"], row["PERIOD"],
                     row["PERIOD_SOURCE"], row["PERIOD_CONFIDENCE"],
                     row["SETTLEMENT"], row["ODDS"]),
                    ("PLAYER_PROP", player, team, "OVER", "0.5", "1ST_HALF",
                     "MARKET_TITLE", "HIGH", "WIN_LOSE", odds),
                )
                accepted, quarantined = partition_semantic_records([row])
                self.assertEqual((accepted, quarantined), ([row], []))

    def test_adjacent_players_keep_row_local_identity_and_odds(self):
        first, second = (parse_real_row(raw)[0] for raw in REAL_FIRST_HALF_OFFSIDES_ROWS[:2])
        self.assertEqual(
            (first["PARTICIPANT"], first["LINE"], first["ODDS"]),
            ("Ezequiel Ponce", "0.5", "1.55"),
        )
        self.assertEqual(
            (second["PARTICIPANT"], second["LINE"], second["ODDS"]),
            ("Fer Nino", "0.5", "1.58"),
        )
        self.assertNotEqual(first["MARKET_INSTANCE_ID"], second["MARKET_INSTANCE_ID"])

    def test_period_and_player_scope_contracts_remain_distinct(self):
        ordinary, _ = parse_market_record(
            category="Statystyki", market_title="Liczba spalonych zawodnika (OPTA)",
            raw_selection="Ezequiel Ponce Powyżej 0,5", odds_str="1.18",
            raw_text="Ezequiel Ponce Powyżej 0,5 1.18", section_title="Elche",
            participant_hint=None, line_hint="", period_hint="", ancestor_title="",
            main_tab="Statystyki", home_team="Elche", away_team="Barcelona",
            container_id="ordinary-row",
        )
        first_half, _ = parse_real_row(REAL_FIRST_HALF_OFFSIDES_ROWS[0])
        self.assertEqual((ordinary["FAMILY"], ordinary["PERIOD"]), ("PLAYER_PROP", "UNKNOWN"))
        self.assertEqual((first_half["FAMILY"], first_half["PERIOD"]), ("PLAYER_PROP", "1ST_HALF"))

        for title in ("Liczba spalonych", "Liczba spalonych w meczu"):
            with self.subTest(title=title):
                self.assertEqual(
                    classify_family(title, "Powyżej 3,5", "", "Elche", "Barcelona")[0],
                    "GENERIC",
                )


if __name__ == "__main__":
    unittest.main()
