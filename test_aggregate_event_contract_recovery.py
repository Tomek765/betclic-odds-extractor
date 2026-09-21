"""Aggregate statistics markets: exact taxonomy, row-local lines, proven periods."""
import unittest
from pathlib import Path

from core import partition_semantic_records
from parser import parse_market_record
from replay import replay_real_prematch


def parse(title: str, selection: str, source_id: str = "real:1"):
    return parse_market_record(
        category="Statystyki", market_title=title, raw_selection=selection,
        odds_str="1.83", raw_text=f"{selection} 1.83", section_title="Rzuty rożne",
        home_team="Elche", away_team="Barcelona", container_id="bounded-stat-market",
        main_tab="Statystyki", market_instance_id="tab:Statystyki|row#0",
        raw_record_id=source_id, source_raw_record_ids=[source_id],
    )


class AggregateEventContractRecovery(unittest.TestCase):
    def test_match_shots_total_is_full_time_event_total(self):
        row, issue = parse("Liczba strzałów w meczu (OPTA)", "Powyżej 20,5")
        self.assertIsNone(issue)
        self.assertEqual((row["FAMILY"], row["SELECTION"], row["LINE"], row["OWNER"],
                          row["PERIOD"], row["PERIOD_SOURCE"], row["SETTLEMENT"]),
                         ("EVENT_TOTAL", "OVER", "20.5", "", "MATCH_INCLUDING_EXTRA_TIME",
                          "BETCLIC_PL_STATISTICS_RULE_20260905", "NO_PUSH"))
        self.assertEqual(partition_semantic_records([row]), ([row], []))

    def test_team_shots_total_uses_only_exact_title_owner(self):
        row, issue = parse("Liczba strzałów w meczu (OPTA) - Barcelona", "Poniżej 12,5")
        self.assertIsNone(issue)
        self.assertEqual((row["FAMILY"], row["SELECTION"], row["LINE"], row["OWNER"],
                          row["PERIOD"], row["SETTLEMENT"]),
                         ("EVENT_TOTAL", "UNDER", "12.5", "Barcelona", "MATCH_INCLUDING_EXTRA_TIME", "NO_PUSH"))

    def test_overtime_beats_in_match_phrase(self):
        row, issue = parse("Liczba fauli w meczu (OPTA) (z dogrywką)", "Powyżej 22,5")
        self.assertIsNone(issue)
        self.assertEqual((row["FAMILY"], row["PERIOD"], row["PERIOD_SOURCE"],
                          row["MARKET_SCOPE"], row["SETTLEMENT"]),
                         ("EVENT_TOTAL", "OTHER", "MARKET_TITLE", "OTHER", "NO_PUSH"))

    def test_without_overtime_is_regular_time_not_other(self):
        row, issue = parse("Rzuty rożne (bez dogrywki) - Elche", "Poniżej 8,5")
        self.assertIsNone(issue)
        self.assertEqual((row["FAMILY"], row["OWNER"], row["PERIOD"], row["MARKET_SCOPE"],
                          row["SETTLEMENT"]),
                         ("EVENT_TOTAL", "Elche", "FULL_TIME", "REGULAR_TIME", "NO_PUSH"))

    def test_unscoped_corner_total_gains_taxonomy_not_period(self):
        row, issue = parse("Rzuty rożne", "Powyżej 7,5")
        self.assertIsNone(issue)
        self.assertEqual((row["FAMILY"], row["SELECTION"], row["LINE"], row["PERIOD"],
                          row["SETTLEMENT"]),
                         ("EVENT_TOTAL", "OVER", "7.5", "FULL_TIME", "NO_PUSH"))
        self.assertEqual(partition_semantic_records([row]), ([row], []))

    def test_integer_event_total_keeps_push_possible_contract(self):
        row, issue = parse("Rzuty rożne", "Powyżej 8")
        self.assertIsNone(issue)
        self.assertEqual(row["SETTLEMENT"], "PUSH_POSSIBLE")

    def test_malformed_total_selection_does_not_enter_event_total(self):
        row, issue = parse("Rzuty rożne", "Dowolny tekst")
        self.assertIsNone(issue)
        self.assertNotEqual(row["FAMILY"], "EVENT_TOTAL")

    def test_exact_card_count_half_is_event_exact(self):
        row, issue = parse("Elche Dokładna liczba kartek - 1. połowa", "3+")
        self.assertIsNone(issue)
        self.assertEqual((row["FAMILY"], row["SELECTION"], row["LINE"], row["OWNER"],
                          row["PERIOD"], row["SETTLEMENT"]),
                         ("EVENT_EXACT", "3+", "", "Elche", "1ST_HALF", "WIN_LOSE"))
        self.assertEqual(partition_semantic_records([row]), ([row], []))

    def test_exact_card_count_without_time_stays_quarantined(self):
        row, issue = parse("Dokładna liczba kartek - Barcelona", "0 - 1")
        self.assertIsNone(issue)
        self.assertEqual((row["FAMILY"], row["OWNER"], row["PERIOD"], row["SETTLEMENT"]),
                         ("EVENT_EXACT", "Barcelona", "UNKNOWN", "WIN_LOSE"))
        self.assertEqual(partition_semantic_records([row]), ([], [row]))

    def test_first_card_half_normalizes_team_and_no_event(self):
        home, issue = parse("Pierwsza kartka- 1. połowa", "Elche")
        self.assertIsNone(issue)
        none, issue = parse("Pierwsza kartka- 1. połowa", "Nikt")
        self.assertIsNone(issue)
        self.assertEqual((home["FAMILY"], home["SELECTION"], home["OWNER"], home["PERIOD"],
                          home["SETTLEMENT"]),
                         ("EVENT_FIRST_LAST", "HOME", "Elche", "1ST_HALF", "WIN_LOSE"))
        self.assertEqual((none["SELECTION"], none["OWNER"]), ("NO_EVENT", ""))

    def test_more_cards_result_recovers_sides_but_not_time(self):
        row, issue = parse("Więcej kartek", "Barcelona")
        self.assertIsNone(issue)
        self.assertEqual((row["FAMILY"], row["SELECTION"], row["OWNER"], row["PERIOD"],
                          row["SETTLEMENT"]),
                         ("EVENT_RESULT", "AWAY", "Barcelona", "FULL_TIME", "WIN_DRAW_LOSE"))
        self.assertEqual(partition_semantic_records([row]), ([row], []))

    def test_saved_replay_preserves_complete_accounting_after_later_repairs(self):
        report = replay_real_prematch(
            Path("diagnostics/raw_before_dedupe_run_1787475817_15748.jsonl")
        )
        accounting = report["production_accounting"]
        self.assertEqual(accounting["SEMANTIC_ACCEPTED_COUNT"]
                         + accounting["SEMANTIC_QUARANTINED_COUNT"], 1394)
        self.assertEqual(accounting["UNACCOUNTED_SOURCE_RECORD_COUNT"], 0)
        self.assertTrue(accounting["ALL_SOURCE_IDS_PRESERVED"])


if __name__ == "__main__":
    unittest.main()
