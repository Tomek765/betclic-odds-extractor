"""FAST4 (2026-10-02, user request): faster capture, no word about left-out offers."""
import unittest

from apex_context_engine.engine import build_context
from apex_context_engine.packet_parser import parse_packet_text
from apex_context_engine.report import render_match_context
from core import _is_bet_builder_tab
from test_package_context_quarantine import odd, with_odds


class BetBuilderTabIsSkipped(unittest.TestCase):
    def test_only_mycombi_is_skipped(self):
        self.assertTrue(_is_bet_builder_tab("MyCombi"))
        self.assertTrue(_is_bet_builder_tab(" mycombi "))
        for name in ("Top", "⚡ Fast", "Wynik", "Strzelcy", "Gole", "Statystyki", "SuperSub", ""):
            self.assertFalse(_is_bet_builder_tab(name), name)


class ContextNeverMentionsLeftOutOffers(unittest.TestCase):
    def test_usable_context_with_left_out_offers_reads_pass(self):
        rows = [odd(FAMILY="GOAL_MARGIN", MARKET="Różnica goli", SELECTION="Remis", SETTLEMENT="UNKNOWN",
                    ODDS="4.00", RAW="Remis 4.00")]
        context = build_context(parse_packet_text(with_odds(*rows)))
        self.assertEqual(context.status, "PASS_WITH_QUARANTINE")
        report = render_match_context(context)
        self.assertIn("STATUS=PASS\n", report)
        self.assertNotIn("QUARANTIN", report)


if __name__ == "__main__":
    unittest.main()
