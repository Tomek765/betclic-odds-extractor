"""Regression contract for known-valid Betclic markets outside model scope."""
import unittest

from core import partition_semantic_records
from parser import parse_market_record


def parsed(title, selection, *, hint="", home="Home FC", away="Away FC"):
    row, unresolved = parse_market_record(
        category="Statystyki", market_title=title, raw_selection=selection,
        odds_str="2.10", raw_text=f"{selection} 2.10", section_title="",
        home_team=home, away_team=away, container_id="test", period_hint=hint,
    )
    assert unresolved is None
    return row


class KnownValidNotModelledContract(unittest.TestCase):
    def test_real_team_scoring_method_is_binary_not_unscoped_goalscorer(self):
        row, unresolved = parse_market_record(
            category="Gole",
            market_title="Strzelą gola głową - Elche",
            raw_selection="Tak",
            odds_str="6.40",
            raw_text="Tak 6.40",
            section_title="Gole - popularne",
            home_team="Elche",
            away_team="Barcelona",
            container_id="box-real-1209",
            ancestor_title="Gole - popularne",
            main_tab="Gole",
            market_instance_id="tab:Gole|sports-markets-single-market[block.marketElement#83]|row#0",
            run_id="run_1787468388_16016",
            event_id="Elche|Barcelona",
            raw_record_id="run_1787468388_16016:1209",
            source_raw_record_ids=["run_1787468388_16016:1209"],
        )

        self.assertIsNone(unresolved)
        accepted, quarantined = partition_semantic_records([row])
        self.assertEqual(
            (row["FAMILY"], row["OWNER"], row["PERIOD"], row["SETTLEMENT"]),
            ("BINARY_EVENT", "Elche", "FULL_TIME", "WIN_LOSE"),
        )
        self.assertEqual((accepted, quarantined), ([row], []))
        self.assertEqual(row["source_raw_record_ids"], ["run_1787468388_16016:1209"])

    def test_closed_specialty_families_are_not_quarantined(self):
        cases = [
            ("Zwycięzca rywalizacji", "Home FC", "QUALIFICATION_WINNER", "WIN_LOSE"),
            ("Sposób awansu", "Home FC w 90 min.", "QUALIFICATION_METHOD", "WIN_LOSE"),
            ("Dogrywka - Tak/Nie", "Tak", "BINARY_EVENT", "WIN_LOSE"),
            ("Pierwszy Rzut Rogny", "Home FC", "EVENT_FIRST_LAST", "WIN_LOSE"),
            ("Rzuty rożne - Przedziały", "9 - 11", "EVENT_RANGE", "WIN_LOSE"),
            ("Rzuty rożne nieparz./parz.", "Parzyste", "EVENT_PARITY", "WIN_LOSE"),
            ("Rzuty rożne w- 1. połowa", "Remis", "EVENT_RESULT", "WIN_DRAW_LOSE"),
        ]
        for title, selection, family, settlement in cases:
            with self.subTest(title=title):
                row = parsed(title, selection)
                self.assertEqual((row["FAMILY"], row["SETTLEMENT"]), (family, settlement))

    def test_unproven_shapes_remain_fail_closed(self):
        self.assertEqual(parsed("Sposób awansu", "Home FC someday")["SETTLEMENT"], "UNKNOWN")
        self.assertEqual(parsed("Dogrywka - Tak/Nie", "Maybe")["SETTLEMENT"], "UNKNOWN")
        self.assertEqual(parsed("Rzuty rożne - Przedziały", "many")["SETTLEMENT"], "UNKNOWN")
        self.assertEqual(parsed("Rzuty rożne w- 1. połowa", "Third team")["SETTLEMENT"], "UNKNOWN")

    def test_period_evidence_is_not_erased(self):
        self.assertEqual(parsed("Rzuty rożne w- 1. połowa", "Home FC")["PERIOD"], "1ST_HALF")
