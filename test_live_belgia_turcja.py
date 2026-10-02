"""Live 2026-10-02 (Belgia - Turcja, FAST5): three more new Top card sentences.

Every live run brought new Betclic Top wording ("Turcja powyżej 2,5 kartek w
meczu", "A lub B strzeli gola", "Gol w przedziale czasu Przerwa - 59:59") and
each one degraded the whole capture to PARTIAL.  A proven Top card is fully
captured (sentence and price); only its betting semantics may be unknown.  It
is therefore an explicit, accounted exclusion (UNRECOGNIZED_TOP_CARD), never
priced and never guessed, and it does not mark the capture incomplete.  Rows
outside the Top card boundary keep failing closed as MISSING_MARKET_HEADER.
"""
import unittest
import warnings
from unittest.mock import MagicMock, patch

from apex_context_engine.engine import build_context
from apex_context_engine.packet_parser import parse_packet_text
from apex_context_engine.report import quarantine_diagnostics
from core import BetclicOddsExtractor, canonical_export_boundary, semantic_quarantine_ledger
from parser import (UNRECOGNIZED_TOP_CARD_TITLE, headerless_top_card_exclusion,
                    neutralize_unrecognized_top_card, parse_market_record)

INSTANCE = ("tab:Top|sports-markets-single-market[block.marketElement#0]|"
            "div[marketBox.is-goodDeals#0]|sports-matrix-markets[#1]|row#{}")
LIVE = (("Turcja powyżej 2,5 kartek w meczu", "1.72"),
        ("Dodi Lukebakio lub Deniz Gul strzeli gola", "2.12"),
        ("Gol w przedziale czasu Przerwa - 59:59", "2.23"),
        # Free text that would look like an ordinary total if it were read.
        ("Belgia powyżej 2,5 goli w meczu i Turcja strzeli gola", "3.10"))


def card(text, odds, index):
    instance = INSTANCE.format(index)
    exclusion = headerless_top_card_exclusion(text, "Top", instance)
    row, issue = parse_market_record(
        category="Top", market_title=exclusion["market_title"], raw_selection=exclusion["raw_selection"],
        odds_str=odds, raw_text=f"{text} {odds}", section_title="", home_team="Belgia", away_team="Turcja",
        container_id=instance, market_instance_id=instance, main_tab="Top",
        raw_record_id=f"r{index}", source_raw_record_ids=[f"r{index}"])
    assert issue is None, issue
    return neutralize_unrecognized_top_card(row)


class UnrecognizedTopCardIsAnExplicitExclusion(unittest.TestCase):
    def test_live_cards_are_excluded_with_their_own_reason(self):
        rows = [card(text, odds, i) for i, (text, odds) in enumerate(LIVE)]
        _canonical, accepted, quarantined, _groups, _suppressed = canonical_export_boundary(rows, "Belgia", "Turcja")
        self.assertEqual(accepted, [])
        self.assertEqual(len(quarantined), len(LIVE))
        ledger = semantic_quarantine_ledger(quarantined)
        self.assertEqual({entry["reason"] for entry in ledger}, {"UNRECOGNIZED_TOP_CARD"})
        self.assertEqual([float(entry["odds"]) for entry in ledger], sorted(
            [float(entry["odds"]) for entry in ledger], key=[float(o) for _t, o in LIVE].index))
        for entry in ledger:
            self.assertEqual((entry["family"], entry["period"], entry["market"]),
                             ("GENERIC", "UNKNOWN", UNRECOGNIZED_TOP_CARD_TITLE))

    def test_only_the_proven_top_card_boundary_is_excluded(self):
        self.assertIsNone(headerless_top_card_exclusion("Turcja powyżej 2,5 kartek w meczu", "Gole", INSTANCE.format(0)))
        self.assertIsNone(headerless_top_card_exclusion("Turcja powyżej 2,5 kartek w meczu", "Top", "tab:Top|ordinary-market"))
        self.assertIsNone(headerless_top_card_exclusion("   ", "Top", INSTANCE.format(0)))


class CaptureStaysCompleteWithUnknownTopCards(unittest.TestCase):
    def run_capture(self, extra_rows):
        header = MagicMock(); header.inner_text.return_value = "Belgia - Turcja"; header.is_visible.return_value = False
        tab = MagicMock(); tab.inner_text.return_value = "Top"; tab.query_selector.return_value = None
        tab.get_attribute.return_value = "tab_item isActive"; tab.is_visible.return_value = True
        page = MagicMock(); page.goto.return_value = MagicMock(status=200)
        page.title.return_value = "Obstawianie Belgia - Turcja | Betclic"
        page.query_selector.side_effect = lambda sel: header if ("h1" in sel or "header" in sel) else None
        page.query_selector_all.side_effect = lambda sel: [tab] if ("tab" in sel or "category" in sel) else []
        page.content.return_value = "<html><body></body></html>"
        rows = [{"container_id": "box_1", "category": "Top", "market": "Suma goli 2.5", "selection": "Powyżej 2.5",
                 "section_title": "", "odds": "1.85", "raw": "Powyżej 2.5 1.85", "missing_header": False,
                 "source_index": 1}] + extra_rows

        def evaluate(script, *args):
            s = str(script)
            if "NO_EVENT_HEADER" in s:
                return {"status": "PREMATCH", "proof": "mock-event-header"}
            if "innerHeight" in s:
                return 800
            if "scrollHeight" in s:
                return 1000
            if "currentTabName" in s or len(args) > 0:
                return [dict(row) for row in rows]
            if "interactive" in s or "seenButtons" in s:
                return {"interactive_control_count": len(rows), "priced_candidate_count": len(rows),
                        "unpriced_control_count": 0, "selectable_count": len(rows),
                        "remaining_closed": 0, "remaining_more": 0}
            return None

        page.evaluate.side_effect = evaluate
        context = MagicMock(); context.pages = [page]
        pw = MagicMock(); pw.chromium.launch_persistent_context.return_value = context
        pw_cm = MagicMock(); pw_cm.__enter__.return_value = pw
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with patch("playwright.sync_api.sync_playwright", return_value=pw_cm), \
                 patch("core.find_chrome_exe", return_value=None):
                return BetclicOddsExtractor().extract("https://www.betclic.pl/pilka-nozna-sfootball/test-c1/belgia-turcja-m123")

    def headerless(self, text, odds, index, instance=None):
        return {"container_id": f"deal_{index}", "category": "Top", "market": "", "selection": text,
                "section_title": "", "odds": odds, "raw": f"{text} {odds}", "missing_header": True,
                "market_instance_id": instance or INSTANCE.format(index), "source_index": 2 + index}

    def test_unknown_top_cards_do_not_make_the_capture_partial(self):
        result = self.run_capture([self.headerless(text, odds, i) for i, (text, odds) in enumerate(LIVE)])
        self.assertEqual(result.get("status"), "GOTOWE", result.get("incomplete_reasons"))
        self.assertEqual(result.get("unresolved_count"), 0)
        packet = result.get("packet_text", "")
        self.assertEqual(packet.count('REASON="UNRECOGNIZED_TOP_CARD"'), len(LIVE))
        package = result.get("llm_packet_text", "")
        for text, _odds in LIVE:
            self.assertNotIn(text, package)
        explained = quarantine_diagnostics(build_context(parse_packet_text(packet)))
        self.assertEqual([(row["reason_code"], row["source_stage"]) for row in explained],
                         [("UNRECOGNIZED_TOP_CARD", "EXTRACTOR_SEMANTIC")] * len(LIVE))

    def test_headerless_row_outside_top_cards_still_fails_closed(self):
        result = self.run_capture([self.headerless("Coś bez nagłówka", "2.00", 0, "tab:Top|ordinary-market|row#0")])
        self.assertEqual(result.get("unresolved_count"), 1)
        self.assertIn("UNRESOLVED", result.get("incomplete_reasons") or [])


if __name__ == "__main__":
    unittest.main()
