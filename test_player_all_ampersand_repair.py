"""Exact ALL-scorer offers split ampersand participants without inventing OR."""
import unittest
from pathlib import Path

from parser import parse_market_record
from replay import replay_real_prematch


def parse(title: str, selection: str):
    return parse_market_record(
        category="Strzelcy", market_title=title, raw_selection=selection,
        odds_str="3.20", raw_text=f"{selection} 3.20", section_title="Strzelcy",
        home_team="Elche", away_team="Barcelona", container_id="exact-all-scorers",
        main_tab="Strzelcy", market_instance_id="tab:Strzelcy|row#0",
        raw_record_id="real:1", source_raw_record_ids=["real:1"],
    )


class PlayerAllAmpersandRepair(unittest.TestCase):
    def test_two_and_three_player_all_offers_split_exact_arity(self):
        two, issue = parse("Obaj gracze strzelą", "L. Yamal & Raphinha")
        self.assertIsNone(issue)
        three, issue = parse("Wszyscy strzelą", "L. Yamal & A. Gordon & Raphinha")
        self.assertIsNone(issue)
        self.assertEqual(
            (two["FAMILY"], two["SELECTION"], two["PARTICIPANT"],
             two["PARTICIPANTS"], two["SCORER_SCOPE"], two["PERIOD"]),
            ("PLAYER_COMBINATION", "ALL_PLAYERS_SCORE", "",
             ["L. Yamal", "Raphinha"], "ANYTIME", "FULL_TIME"),
        )
        self.assertEqual(
            (three["SELECTION"], three["PARTICIPANT"], three["PARTICIPANTS"]),
            ("ALL_PLAYERS_SCORE", "", ["L. Yamal", "A. Gordon", "Raphinha"]),
        )

    def test_half_and_both_halves_keep_exact_period_scope(self):
        first, issue = parse("Obaj gracze strzelą w 1. połowa", "L. Yamal & Raphinha")
        self.assertIsNone(issue)
        second, issue = parse("Obaj gracze strzelą w 2. połowa", "L. Yamal & Raphinha")
        self.assertIsNone(issue)
        both, issue = parse("Obaj gracze strzelą w obu połowach", "L. Yamal & Raphinha")
        self.assertIsNone(issue)
        self.assertEqual((first["SELECTION"], first["PERIOD"], first["SCORER_SCOPE"]),
                         ("ALL_PLAYERS_SCORE", "1ST_HALF", "ANYTIME"))
        self.assertEqual((second["SELECTION"], second["PERIOD"], second["SCORER_SCOPE"]),
                         ("ALL_PLAYERS_SCORE", "2ND_HALF", "ANYTIME"))
        self.assertEqual((both["SELECTION"], both["PERIOD"], both["SCORER_SCOPE"]),
                         ("ALL_PLAYERS_SCORE_BOTH_HALVES", "FULL_TIME",
                          "ALL_SCORE_BOTH_HALVES"))

    def test_wrong_arity_does_not_enter_closed_all_contract(self):
        row, issue = parse("Wszyscy strzelą", "L. Yamal & Raphinha")
        self.assertIsNone(issue)
        self.assertNotEqual(row["SELECTION"], "ALL_PLAYERS_SCORE")

    def test_saved_replay_repairs_all_27_audited_rows(self):
        report = replay_real_prematch(
            Path("diagnostics/raw_before_dedupe_run_1787475817_15748.jsonl")
        )
        rows = report["odds"]
        by_source = {
            source: row for row in rows for source in row["source_raw_record_ids"]
        }
        ids = set(range(590, 596)) | set(range(629, 632)) | set(range(842, 860))
        repaired = [by_source[f"run_1787475817_15748:{value}"] for value in ids]
        self.assertEqual(len(repaired), 27)
        self.assertTrue(all(row["PARTICIPANT"] == "" for row in repaired))
        self.assertEqual({len(row["PARTICIPANTS"]) for row in repaired}, {2, 3})
        self.assertTrue(all(row["SELECTION"].startswith("ALL_PLAYERS_SCORE")
                            for row in repaired))
        self.assertEqual(sum(row["SCORER_SCOPE"] == "ALL_SCORE_BOTH_HALVES"
                             for row in repaired), 6)
        accounting = report["production_accounting"]
        self.assertEqual(accounting["SEMANTIC_ACCEPTED_COUNT"]
                         + accounting["SEMANTIC_QUARANTINED_COUNT"], 1394)
        self.assertEqual(accounting["UNACCOUNTED_SOURCE_RECORD_COUNT"], 0)


if __name__ == "__main__":
    unittest.main()
