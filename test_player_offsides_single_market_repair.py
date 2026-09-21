"""Real Elche–Barcelona regression for inline single-market player offsides."""
import unittest

from core import partition_semantic_records, semantic_quarantine_ledger
from parser import classify_family, parse_market_record


# Lossless reductions of fresh run_1787472984_14840.  In the real DOM each
# selection is bounded by its own div.marketBox_lineSelection.  The player,
# OVER token and line are co-located in that row's p.marketBox_label; its odds
# button is a sibling inside the same row.  The team title is group/owner
# context, not the participant.
REAL_OFFSIDES_ROWS = (
    {
        "raw_record_id": "run_1787472984_14840:425",
        "category": "SuperSub",
        "market": "Liczba spalonych zawodnika (Supersub)",
        "section_title": "Elche",
        "selection": "Ezequiel Ponce Powyżej 0,5",
        "odds": "1.12",
        "market_instance_id": "tab:SuperSub|sports-markets-single-market[block.marketElement#23]|sports-split-card[#2]|row#1|div[marketBox_lineSelection#1]",
    },
    {
        "raw_record_id": "run_1787472984_14840:426",
        "category": "SuperSub",
        "market": "Liczba spalonych zawodnika (Supersub)",
        "section_title": "Elche",
        "selection": "Fer Nino Powyżej 0,5",
        "odds": "1.12",
        "market_instance_id": "tab:SuperSub|sports-markets-single-market[block.marketElement#23]|sports-split-card[#2]|row#2|div[marketBox_lineSelection#2]",
    },
    {
        "raw_record_id": "run_1787472984_14840:912",
        "category": "Strzelcy",
        "market": "Liczba spalonych zawodnika (OPTA)",
        "section_title": "Elche",
        "selection": "Ezequiel Ponce Powyżej 0,5",
        "odds": "1.18",
        "market_instance_id": "tab:Strzelcy|sports-markets-single-market[block.marketElement#77]|sports-split-card[#1]|row#1|div[marketBox_lineSelection#1]",
    },
    {
        "raw_record_id": "run_1787472984_14840:913",
        "category": "Strzelcy",
        "market": "Liczba spalonych zawodnika (OPTA)",
        "section_title": "Elche",
        "selection": "Fer Nino Powyżej 0,5",
        "odds": "1.19",
        "market_instance_id": "tab:Strzelcy|sports-markets-single-market[block.marketElement#77]|sports-split-card[#1]|row#2|div[marketBox_lineSelection#2]",
    },
    {
        "raw_record_id": "run_1787472984_14840:1529",
        "category": "Statystyki",
        "market": "Liczba spalonych zawodnika (OPTA)",
        "section_title": "Elche",
        "selection": "Ezequiel Ponce Powyżej 0,5",
        "odds": "1.18",
        "market_instance_id": "tab:Statystyki|sports-markets-single-market[block.marketElement#75]|sports-split-card[#1]|row#1|div[marketBox_lineSelection#1]",
    },
    {
        "raw_record_id": "run_1787472984_14840:1532",
        "category": "Statystyki",
        "market": "Liczba spalonych zawodnika (OPTA)",
        "section_title": "Barcelona",
        "selection": "Karim Adeyemi Powyżej 0,5",
        "odds": "2.05",
        "market_instance_id": "tab:Statystyki|sports-markets-single-market[block.marketElement#75]|sports-split-card[#2]|row#1|div[marketBox_lineSelection#1]",
    },
)


def parse_real_row(raw):
    return parse_market_record(
        category=raw["category"], market_title=raw["market"],
        raw_selection=raw["selection"], odds_str=raw["odds"],
        raw_text=f'{raw["selection"]} {raw["odds"]}',
        section_title=raw["section_title"], participant_hint=None, line_hint="",
        period_hint="", ancestor_title="", main_tab=raw["category"],
        home_team="Elche", away_team="Barcelona", container_id="bounded-single-market-row",
        market_instance_id=raw["market_instance_id"], raw_record_id=raw["raw_record_id"],
        source_raw_record_ids=[raw["raw_record_id"]],
    )


class PlayerOffsidesSingleMarketRepair(unittest.TestCase):
    def test_real_inline_offsides_rows_have_player_prop_semantics(self):
        expected_players = (
            "Ezequiel Ponce", "Fer Nino", "Ezequiel Ponce",
            "Fer Nino", "Ezequiel Ponce", "Karim Adeyemi",
        )
        for raw, expected_player in zip(REAL_OFFSIDES_ROWS, expected_players):
            with self.subTest(raw_record_id=raw["raw_record_id"]):
                row, unresolved = parse_real_row(raw)
                self.assertIsNone(unresolved)
                self.assertEqual(
                    (row["FAMILY"], row["PARTICIPANT"], row["OWNER"],
                     row["SELECTION"], row["LINE"], row["ODDS"]),
                    ("PLAYER_PROP", expected_player, raw["section_title"],
                     "OVER", "0.5", raw["odds"]),
                )
                self.assertEqual((row["PERIOD"], row["SETTLEMENT"]), ("UNKNOWN", "WIN_LOSE"))
                accepted, quarantined = partition_semantic_records([row])
                self.assertEqual(accepted, [])
                self.assertEqual(
                    semantic_quarantine_ledger(quarantined)[0]["reason"],
                    "UNCONFIRMED_PLAYER_PROP_PERIOD",
                )

    def test_adjacent_players_keep_their_own_row_scope_and_odds(self):
        first, second = (parse_real_row(raw)[0] for raw in REAL_OFFSIDES_ROWS[2:4])
        self.assertEqual(
            (first["PARTICIPANT"], first["LINE"], first["SELECTION"], first["ODDS"]),
            ("Ezequiel Ponce", "0.5", "OVER", "1.18"),
        )
        self.assertEqual(
            (second["PARTICIPANT"], second["LINE"], second["SELECTION"], second["ODDS"]),
            ("Fer Nino", "0.5", "OVER", "1.19"),
        )
        self.assertNotEqual(first["MARKET_INSTANCE_ID"], second["MARKET_INSTANCE_ID"])

    def test_aggregate_offsides_is_event_total_but_ambiguous_player_titles_stay_generic(self):
        cases = (
            ("Liczba spalonych w meczu (OPTA)", "Powyżej 3,5", "EVENT_TOTAL"),
            ("Spalone zawodnika", "Jan Kowalski Powyżej 0,5", "GENERIC"),
            ("Zawodnik na spalonym", "Jan Kowalski", "GENERIC"),
        )
        for title, selection, expected in cases:
            with self.subTest(title=title):
                self.assertEqual(classify_family(title, selection, "", "A", "B")[0], expected)


if __name__ == "__main__":
    unittest.main()
