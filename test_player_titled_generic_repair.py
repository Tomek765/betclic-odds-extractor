"""Real Elche–Barcelona regression for bounded player-tackles sliders."""
import unittest

from core import partition_semantic_records, semantic_quarantine_ledger
from parser import classify_family, parse_market_record


# Lossless reductions of run_1787471920_14692 records :431–:433, :918–:920
# and :1633–:1635.  Participant, line, selection and odds are direct children
# of each record's own sports-slider-value; the DOM exposes no period evidence.
REAL_TACKLE_ROWS = (
    {
        "raw_record_id": "run_1787471920_14692:431",
        "category": "SuperSub",
        "market": "Liczba odbiorów zawodnika (Supersub)",
        "participant_hint": "Javi Morcillo",
        "selection": "Powyżej 2,5",
        "line_hint": "2.5",
        "odds": "1.30",
        "raw": "Javi Morcillo Powyżej 2,5 1.30",
        "market_instance_id": "tab:SuperSub|sports-slider-market[block.marketElement#25]|row#0|sports-slider-value[marketBox_lineSelection#0]",
    },
    {
        "raw_record_id": "run_1787471920_14692:432",
        "category": "SuperSub",
        "market": "Liczba odbiorów zawodnika (Supersub)",
        "participant_hint": "Rodri",
        "selection": "Powyżej 2,5",
        "line_hint": "2.5",
        "odds": "1.32",
        "raw": "Rodri Powyżej 2,5 1.32",
        "market_instance_id": "tab:SuperSub|sports-slider-market[block.marketElement#25]|row#1|sports-slider-value[marketBox_lineSelection#1]",
    },
    {
        "raw_record_id": "run_1787471920_14692:919",
        "category": "Strzelcy",
        "market": "Liczba odbiorów zawodnika (OPTA)",
        "participant_hint": "Marc Casado Torras",
        "selection": "Powyżej 2,5",
        "line_hint": "2.5",
        "odds": "1.50",
        "raw": "Marc Casado Torras Powyżej 2,5 1.50",
        "market_instance_id": "tab:Strzelcy|sports-slider-market[block.marketElement#78]|row#1|sports-slider-value[marketBox_lineSelection#1]",
    },
    {
        "raw_record_id": "run_1787471920_14692:1635",
        "category": "Statystyki",
        "market": "Liczba odbiorów zawodnika (OPTA)",
        "participant_hint": "Federico Redondo",
        "selection": "Powyżej 2,5",
        "line_hint": "2.5",
        "odds": "1.50",
        "raw": "Federico Redondo Powyżej 2,5 1.50",
        "market_instance_id": "tab:Statystyki|sports-slider-market[block.marketElement#83]|row#2|sports-slider-value[marketBox_lineSelection#2]",
    },
)


def parse_real_row(raw):
    return parse_market_record(
        category=raw["category"], market_title=raw["market"],
        raw_selection=raw["selection"], odds_str=raw["odds"], raw_text=raw["raw"],
        section_title="", participant_hint=raw["participant_hint"], line_hint=raw["line_hint"],
        period_hint="", ancestor_title="", main_tab=raw["category"],
        home_team="Elche", away_team="Barcelona", container_id="bounded-slider",
        market_instance_id=raw["market_instance_id"], raw_record_id=raw["raw_record_id"],
        source_raw_record_ids=[raw["raw_record_id"]],
    )


class PlayerTacklesTaxonomyRepair(unittest.TestCase):
    def test_real_bounded_tackles_sliders_have_player_prop_semantics(self):
        for raw in REAL_TACKLE_ROWS:
            with self.subTest(raw_record_id=raw["raw_record_id"]):
                row, unresolved = parse_real_row(raw)
                self.assertIsNone(unresolved)
                self.assertEqual(
                    (row["FAMILY"], row["PARTICIPANT"], row["SELECTION"], row["LINE"], row["ODDS"]),
                    ("PLAYER_PROP", raw["participant_hint"], "OVER", "2.5", raw["odds"]),
                )
                self.assertEqual((row["PERIOD"], row["SETTLEMENT"]), ("UNKNOWN", "WIN_LOSE"))
                accepted, quarantined = partition_semantic_records([row])
                self.assertEqual(accepted, [])
                self.assertEqual(
                    semantic_quarantine_ledger(quarantined)[0]["reason"],
                    "UNCONFIRMED_PLAYER_PROP_PERIOD",
                )

    def test_adjacent_players_keep_separate_bounded_scope(self):
        first, second = (parse_real_row(raw)[0] for raw in REAL_TACKLE_ROWS[:2])
        self.assertEqual((first["PARTICIPANT"], second["PARTICIPANT"]), ("Javi Morcillo", "Rodri"))
        self.assertNotEqual(first["MARKET_INSTANCE_ID"], second["MARKET_INSTANCE_ID"])

    def test_neighboring_non_player_tackle_titles_remain_generic(self):
        self.assertEqual(classify_family("Liczba odbiorów w meczu (OPTA)", "Powyżej 20,5", "", "A", "B")[0], "GENERIC")
        self.assertEqual(classify_family("Odbiory", "Powyżej 5,5", "", "A", "B")[0], "GENERIC")
        self.assertEqual(classify_family("Zawodnik wykona akcję", "Jan Kowalski", "", "A", "B")[0], "GENERIC")


if __name__ == "__main__":
    unittest.main()
