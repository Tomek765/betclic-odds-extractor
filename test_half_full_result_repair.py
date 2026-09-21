"""Half/full ordered result pairs must survive team alias canonicalisation."""
import unittest
from pathlib import Path

from parser import parse_market_record
from replay import replay_real_prematch


def parse(selection: str):
    return parse_market_record(
        category="Wynik", market_title="Wynik Meczu Połowa / Cały",
        raw_selection=selection, odds_str="12.25", raw_text=f"{selection} 12.25",
        section_title="Wynik - popularne", home_team="Elche", away_team="Barcelona",
        container_id="bounded-result", main_tab="Wynik",
        market_instance_id="tab:Wynik|row#0", raw_record_id="real:253",
        source_raw_record_ids=["real:253"],
    )


class HalfFullResultRepair(unittest.TestCase):
    def test_each_ordered_component_is_preserved(self):
        expectations = {
            "Elche / Elche": "HOME_HOME",
            "Remis/ Elche": "DRAW_HOME",
            "Barcelona / Elche": "AWAY_HOME",
        }
        for source, expected in expectations.items():
            with self.subTest(source=source):
                row, issue = parse(source)
                self.assertIsNone(issue)
                self.assertEqual((row["FAMILY"], row["SELECTION"], row["OWNER"],
                                  row["PERIOD"], row["SETTLEMENT"]),
                                 ("HALF_FULL_RESULT", expected, "", "FULL_TIME", "WIN_LOSE"))

    def test_atomic_event_team_alias_still_canonicalises(self):
        row, issue = parse_market_record(
            category="Wynik", market_title="Wynik meczu", raw_selection="El che",
            odds_str="2.00", raw_text="El che 2.00", section_title="",
            home_team="Elche", away_team="Barcelona", container_id="atomic",
        )
        self.assertIsNone(issue)
        self.assertEqual((row["FAMILY"], row["SELECTION"], row["OWNER"]),
                         ("1X2", "HOME", "Elche"))

    def test_saved_replay_keeps_all_three_real_pairs_distinct(self):
        report = replay_real_prematch(
            Path("diagnostics/raw_before_dedupe_run_1787475817_15748.jsonl")
        )
        rows = [row for row in report["odds"] if row["MARKET"] ==
                "Wynik Meczu Połowa / Cały"]
        self.assertEqual(len(rows), 3)
        self.assertEqual({row["SELECTION"] for row in rows},
                         {"HOME_HOME", "DRAW_HOME", "AWAY_HOME"})
        self.assertEqual({row["source_raw_record_ids"][0] for row in rows},
                         {"run_1787475817_15748:253", "run_1787475817_15748:254",
                          "run_1787475817_15748:255"})


if __name__ == "__main__":
    unittest.main()
