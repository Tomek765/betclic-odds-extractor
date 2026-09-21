"""Real regression for explicit regular-time scorer/assister role pairs."""
import unittest

from core import partition_semantic_records
from parser import parse_market_record


TITLE = "Strzelec bramki i zawodnik, który zaliczy przy niej asystę (czas reg.)"
REAL_ROWS = (
    ("run_1787475817_15748:674", "Elche", "F. Nino (G) i G. Diangana (A)", "28"),
    ("run_1787475817_15748:675", "Elche", "F. Nino (G) i L. Cepeda (A)", "30"),
    ("run_1787475817_15748:676", "Elche", "E. Ponce (G) i G. Diangana (A)", "30"),
    ("run_1787475817_15748:677", "Barcelona", "Raphinha (G) i L. Yamal (A)", "5.90"),
    ("run_1787475817_15748:678", "Barcelona", "L. Yamal (G) i Raphinha (A)", "6.00"),
    ("run_1787475817_15748:679", "Barcelona", "L. Yamal (G) i A. Gordon (A)", "7.25"),
)


def parse_row(raw):
    source_id, team, selection, odds = raw
    return parse_market_record(
        category="Strzelcy", market_title=TITLE, raw_selection=selection,
        odds_str=odds, raw_text=f"{selection} {odds}", section_title=team,
        participant_hint=None, line_hint="", period_hint="", ancestor_title="Strzelec",
        main_tab="Strzelcy", home_team="Elche", away_team="Barcelona",
        container_id="bounded-scorer-assister-row",
        market_instance_id=f"tab:Strzelcy|single[scorerAssister]|{team}|{source_id}",
        raw_record_id=source_id, source_raw_record_ids=[source_id],
    )


class ScorerAssisterPairRepair(unittest.TestCase):
    def test_all_six_rows_have_role_pair_regular_time_semantics(self):
        for raw in REAL_ROWS:
            source_id, team, selection, odds = raw
            scorer, assister = selection.split(" i ", 1)
            with self.subTest(source_id=source_id):
                row, unresolved = parse_row(raw)
                self.assertIsNone(unresolved)
                self.assertEqual(
                    (row["FAMILY"], row["PARTICIPANT"], row["PARTICIPANTS"],
                     row["OWNER"], row["SELECTION"], row["LINE"], row["PERIOD"],
                     row["PERIOD_SOURCE"], row["PERIOD_CONFIDENCE"],
                     row["MARKET_SCOPE"], row["SETTLEMENT"], row["SCORER_SCOPE"],
                     row["COLUMN_SEMANTICS_STATUS"], row["ODDS"]),
                    ("PLAYER_COMBINATION", "", [scorer, assister], team,
                     "SCORER_AND_ASSISTER", "", "FULL_TIME", "MARKET_TITLE",
                     "MEDIUM", "REGULAR_TIME", "WIN_LOSE", "", "NOT_APPLICABLE",
                     odds),
                )
                accepted, quarantined = partition_semantic_records([row])
                self.assertEqual((accepted, quarantined), ([row], []))

    def test_reversed_roles_remain_distinct(self):
        first = parse_row(REAL_ROWS[3])[0]
        reversed_roles = parse_row(REAL_ROWS[4])[0]
        self.assertNotEqual(first["PARTICIPANTS"], reversed_roles["PARTICIPANTS"])
        self.assertEqual(first["ODDS"], "5.90")
        self.assertEqual(reversed_roles["ODDS"], "6.00")

    def test_similar_title_without_explicit_regular_time_is_not_upgraded(self):
        row, _ = parse_market_record(
            category="Strzelcy", market_title=TITLE.replace(" (czas reg.)", ""),
            raw_selection="Raphinha (G) i L. Yamal (A)", odds_str="5.90",
            raw_text="Raphinha (G) i L. Yamal (A) 5.90", section_title="Barcelona",
            home_team="Elche", away_team="Barcelona", container_id="negative",
        )
        self.assertNotEqual(row["FAMILY"], "PLAYER_COMBINATION")


if __name__ == "__main__":
    unittest.main()
