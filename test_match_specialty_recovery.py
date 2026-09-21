"""Exact match-specialty contracts: recover proof, preserve unknown periods."""
import unittest
from pathlib import Path

from core import partition_semantic_records
from parser import parse_market_record
from replay import replay_real_prematch


def parse(title: str, selection: str, source_id: str = "real:1"):
    return parse_market_record(
        category="Gole", market_title=title, raw_selection=selection,
        odds_str="2.05", raw_text=f"{selection} 2.05", section_title="",
        home_team="Elche", away_team="Barcelona", container_id="bounded-market",
        main_tab="Gole", market_instance_id="tab:Gole|row#0",
        raw_record_id=source_id, source_raw_record_ids=[source_id],
    )


class MatchSpecialtyRecovery(unittest.TestCase):
    def test_headed_goal_first_half_is_complete_binary_event(self):
        row, issue = parse("Gol głową - 1. połowa", "Tak", "real:1213")
        self.assertIsNone(issue)
        self.assertEqual((row["FAMILY"], row["SELECTION"], row["PERIOD"],
                          row["PERIOD_SOURCE"], row["SETTLEMENT"]),
                         ("BINARY_EVENT", "Tak", "1ST_HALF", "MARKET_TITLE", "WIN_LOSE"))
        self.assertEqual(partition_semantic_records([row]), ([row], []))

    def test_free_kick_in_match_is_complete_binary_event(self):
        row, issue = parse("Gol bezpośrednio z rzutu wolnego w meczu", "Tak", "real:1219")
        self.assertIsNone(issue)
        self.assertEqual((row["FAMILY"], row["PERIOD"], row["PERIOD_SOURCE"], row["SETTLEMENT"]),
                         ("BINARY_EVENT", "FULL_TIME", "MARKET_TITLE", "WIN_LOSE"))
        self.assertEqual(partition_semantic_records([row]), ([row], []))

    def test_both_halves_heading_is_full_span_compound(self):
        row, issue = parse("Gole głową w obu połowach", "Tak", "real:1217")
        self.assertIsNone(issue)
        self.assertEqual((row["FAMILY"], row["SELECTION"], row["PERIOD"], row["SETTLEMENT"]),
                         ("COMPOUND_LOGIC", "TAK", "FULL_TIME", "WIN_LOSE"))
        self.assertEqual(partition_semantic_records([row]), ([row], []))

    def test_exact_binary_titles_without_time_gain_settlement_not_period(self):
        for title, selection in (("Sędzia sprawdzi sytuację na VAR (podejdzie do monitora)", "Tak"),
                                 ("Bramka rezerwowego", "Nie"),
                                 ("Hat-trick", "Tak"), ("Gol Głową", "Nie")):
            with self.subTest(title=title):
                row, issue = parse(title, selection)
                self.assertIsNone(issue)
                self.assertEqual((row["FAMILY"], row["PERIOD"], row["SETTLEMENT"]),
                                 ("BINARY_EVENT", "UNKNOWN", "WIN_LOSE"))
                self.assertEqual(partition_semantic_records([row]), ([], [row]))

    def test_short_goals_title_recovers_total_but_not_time(self):
        row, issue = parse("Gole", "Powyżej 0,5", "real:1181")
        self.assertIsNone(issue)
        self.assertEqual((row["FAMILY"], row["SELECTION"], row["LINE"], row["PERIOD"],
                          row["SETTLEMENT"]),
                         ("GOALS_OU", "OVER", "0.5", "UNKNOWN", "NO_PUSH"))
        self.assertEqual(partition_semantic_records([row]), ([], [row]))

    def test_scoring_method_btts_recovers_contract_but_not_time(self):
        row, issue = parse("Obie drużyny strzelą gola głową", "Tak", "real:1218")
        self.assertIsNone(issue)
        self.assertEqual((row["FAMILY"], row["SELECTION"], row["PERIOD"], row["SETTLEMENT"]),
                         ("COMPOUND_LOGIC", "TAK", "UNKNOWN", "WIN_LOSE"))
        self.assertEqual(partition_semantic_records([row]), ([], [row]))

    def test_unlisted_yes_no_specialty_stays_generic_and_unknown(self):
        row, issue = parse("Nieudokumentowane zdarzenie", "Tak")
        self.assertIsNone(issue)
        self.assertEqual((row["FAMILY"], row["PERIOD"], row["SETTLEMENT"]),
                         ("GENERIC", "UNKNOWN", "UNKNOWN"))

    def test_saved_replay_accepts_only_six_of_eighteen_match_quarantines(self):
        report = replay_real_prematch(
            Path("diagnostics/raw_before_dedupe_run_1787475817_15748.jsonl")
        )
        accounting = report["production_accounting"]
        self.assertEqual(accounting["SEMANTIC_ACCEPTED_COUNT"] +
                         accounting["SEMANTIC_QUARANTINED_COUNT"], 1394)
        # Four match-level Xtra offers also lack a proven payout contract.
        self.assertEqual(accounting["CURRENT_MATCH_MARKET_QUARANTINED_COUNT"], 16)
        self.assertEqual(accounting["UNACCOUNTED_SOURCE_RECORD_COUNT"], 0)
        self.assertEqual(report["unresolved_count"], 0)


if __name__ == "__main__":
    unittest.main()
