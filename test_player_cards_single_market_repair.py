"""Real Elche–Barcelona regression for inline single-market player cards."""
import unittest

from core import partition_semantic_records, semantic_quarantine_ledger
from parser import classify_family, parse_market_record


# Lossless reductions of run_1787475817_15748.  Each tuple points to a real
# div.marketBox_lineSelection where player, OVER token, 0.5 line and odds are
# bounded together.  The split-card title is explicit team-owner evidence.
REAL_PLAYER_CARD_ROWS = (
    ("run_1787475817_15748:419", "SuperSub", "Liczba kartek zawodnika (Supersub)", "Elche", "Matia Barzic", "2.35", "#2", "#1"),
    ("run_1787475817_15748:420", "SuperSub", "Liczba kartek zawodnika (Supersub)", "Elche", "Javi Morcillo", "2.55", "#2", "#2"),
    ("run_1787475817_15748:421", "SuperSub", "Liczba kartek zawodnika (Supersub)", "Elche", "Facundo Buonanotte", "2.55", "#2", "#3"),
    ("run_1787475817_15748:422", "SuperSub", "Liczba kartek zawodnika (Supersub)", "Barcelona", "Gavi", "2.45", "#3", "#1"),
    ("run_1787475817_15748:423", "SuperSub", "Liczba kartek zawodnika (Supersub)", "Barcelona", "Marc Bernal", "2.55", "#3", "#2"),
    ("run_1787475817_15748:424", "SuperSub", "Liczba kartek zawodnika (Supersub)", "Barcelona", "Karim Adeyemi", "2.65", "#3", "#3"),
    ("run_1787475817_15748:1490", "Statystyki", "Liczba kartek zawodnika", "Elche", "Matia Barzic", "2.65", "#1", "#1"),
    ("run_1787475817_15748:1491", "Statystyki", "Liczba kartek zawodnika", "Elche", "Facundo Buonanotte", "2.90", "#1", "#2"),
    ("run_1787475817_15748:1492", "Statystyki", "Liczba kartek zawodnika", "Elche", "Javi Morcillo", "2.90", "#1", "#3"),
    ("run_1787475817_15748:1493", "Statystyki", "Liczba kartek zawodnika", "Barcelona", "Gavi", "2.85", "#2", "#1"),
    ("run_1787475817_15748:1494", "Statystyki", "Liczba kartek zawodnika", "Barcelona", "Marc Bernal", "2.90", "#2", "#2"),
    ("run_1787475817_15748:1495", "Statystyki", "Liczba kartek zawodnika", "Barcelona", "Karim Adeyemi", "3.10", "#2", "#3"),
)

REAL_FIRST_HALF_PLAYER_CARD_ROWS = (
    ("run_1787475817_15748:1496", "Statystyki", "Liczba kartek zawodnika - 1. połowa", "Elche", "Matia Barzic", "5.50", "#1", "#1"),
    ("run_1787475817_15748:1497", "Statystyki", "Liczba kartek zawodnika - 1. połowa", "Elche", "Buba Sangare", "6.00", "#1", "#2"),
    ("run_1787475817_15748:1498", "Statystyki", "Liczba kartek zawodnika - 1. połowa", "Elche", "Javi Morcillo", "6.00", "#1", "#3"),
    ("run_1787475817_15748:1499", "Statystyki", "Liczba kartek zawodnika - 1. połowa", "Barcelona", "Gavi", "5.50", "#2", "#1"),
    ("run_1787475817_15748:1500", "Statystyki", "Liczba kartek zawodnika - 1. połowa", "Barcelona", "Marc Bernal", "6.00", "#2", "#2"),
    ("run_1787475817_15748:1501", "Statystyki", "Liczba kartek zawodnika - 1. połowa", "Barcelona", "Karim Adeyemi", "6.50", "#2", "#3"),
)


def parse_real_row(raw):
    source_id, tab, title, team, player, odds, card_index, row_index = raw
    selection = f"{player} Powyżej 0,5"
    instance = (
        f"tab:{tab}|sports-markets-single-market[block.playerCards]|"
        f"sports-split-card[{card_index}]|row{row_index}|div[marketBox_lineSelection{row_index}]"
    )
    return parse_market_record(
        category=tab, market_title=title, raw_selection=selection,
        odds_str=odds, raw_text=f"{selection} {odds}", section_title=team,
        participant_hint=None, line_hint="", period_hint="", ancestor_title="",
        main_tab=tab, home_team="Elche", away_team="Barcelona",
        container_id="bounded-player-card-row", market_instance_id=instance,
        raw_record_id=source_id, source_raw_record_ids=[source_id],
    )


class PlayerCardsSingleMarketRepair(unittest.TestCase):
    def test_all_real_rows_have_lossless_player_prop_semantics(self):
        for raw in REAL_PLAYER_CARD_ROWS:
            source_id, _, title, team, player, odds, _, _ = raw
            with self.subTest(source_id=source_id):
                row, unresolved = parse_real_row(raw)
                self.assertIsNone(unresolved)
                self.assertEqual(
                    (row["FAMILY"], row["PARTICIPANT"], row["OWNER"],
                     row["SELECTION"], row["LINE"], row["PERIOD"],
                     row["PERIOD_SOURCE"], row["PERIOD_CONFIDENCE"],
                     row["SETTLEMENT"], row["ODDS"]),
                    ("PLAYER_PROP", player, team, "OVER", "0.5", "UNKNOWN" if "Supersub" in title else "MATCH_INCLUDING_EXTRA_TIME",
                     "UNRESOLVED" if "Supersub" in title else "BETCLIC_PL_STATISTICS_RULE_20260905",
                     "LOW" if "Supersub" in title else "HIGH", "WIN_LOSE", odds),
                )
                self.assertEqual(partition_semantic_records([row]), ([], [row]) if "Supersub" in title else ([row], []))

    def test_real_first_half_rows_fix_false_accepts_with_explicit_period(self):
        for raw in REAL_FIRST_HALF_PLAYER_CARD_ROWS:
            source_id, _, _, team, player, odds, _, _ = raw
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

    def test_adjacent_players_keep_row_local_identity_line_and_odds(self):
        for pair in (REAL_PLAYER_CARD_ROWS[:2], REAL_PLAYER_CARD_ROWS[6:8]):
            first, second = (parse_real_row(raw)[0] for raw in pair)
            self.assertEqual(first["PARTICIPANT"], pair[0][4])
            self.assertEqual(second["PARTICIPANT"], pair[1][4])
            self.assertEqual((first["LINE"], second["LINE"]), ("0.5", "0.5"))
            self.assertEqual((first["ODDS"], second["ODDS"]), (pair[0][5], pair[1][5]))
            self.assertNotEqual(first["MARKET_INSTANCE_ID"], second["MARKET_INSTANCE_ID"])

    def test_aggregate_card_markets_never_gain_player_scope(self):
        cases = (
            ("Liczba kartek", "Powyżej 3,5"),
            ("Kartki - Elche", "Powyżej 1,5"),
            ("Dokładna liczba kartek - Barcelona", "2"),
            ("Liczba Kartek - 1. połowa", "Powyżej 1,5"),
        )
        for title, selection in cases:
            with self.subTest(title=title):
                self.assertNotEqual(
                    classify_family(title, selection, "", "Elche", "Barcelona")[0],
                    "PLAYER_PROP",
                )


if __name__ == "__main__":
    unittest.main()
