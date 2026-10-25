"""Live 2026-10-25 Konyaspor - Genclerbirligi: Strzelcy TAB_STATUS_FAIL.

The crawler union held exactly the 354 priced buttons, but the bounded
Strzelcy scroll retry appended its own re-capture (172 rows of the same
buttons) without identity merging: RAW=526 != PRICED=354
(LEDGER_CONSERVATION_GAP).  A re-capture must fold into the union.
"""
import inspect
import unittest

import core
from exhaustive import merge_capture_into_union, selection_identity


def row(player, column, odds, capture):
    return {"market_instance_id": f"tab:Strzelcy|market#4|column:{column}|row#1|cell:btn",
            "market": "Zawodnik strzeli gola lub zaliczy asystę", "selection": player,
            "section_title": "", "ancestor_title": "", "heading_path": "", "column_heading": column,
            "line_hint": "", "period_hint": "", "participant_hint": None,
            "odds": odds, "capture_id": capture, "record_type": "ODD"}


class StrzelcyRetryMergeTest(unittest.TestCase):
    def test_recapture_of_same_buttons_adds_nothing_and_keeps_latest_price(self):
        union = [row("Pedro Mendes", "1 +", "2.95", "cap_1"), row("Sekou Koita", "1 +", "3.00", "cap_1")]
        added = merge_capture_into_union(union, [row("Pedro Mendes", "1 +", "2.90", "cap_9")], "Strzelcy")
        self.assertEqual(added, 0)
        self.assertEqual(len(union), 2)
        self.assertEqual(union[0]["odds"], "2.90")

    def test_recapture_adds_only_unseen_selections(self):
        union = [row("Pedro Mendes", "1 +", "2.95", "cap_1")]
        added = merge_capture_into_union(
            union, [row("Pedro Mendes", "1 +", "2.95", "cap_9"), row("Tiago Gouveia", "1 +", "3.20", "cap_9")],
            "Strzelcy")
        self.assertEqual((added, len(union)), (1, 2))
        self.assertEqual(len({selection_identity(item) for item in union}), 2)

    def test_complete_recapture_becomes_the_stable_snapshot(self):
        union = [row("Pedro Mendes", "1 +", "2.95", "cap_1"), row("Sekou Koita", "1 +", "3.00", "cap_2")]
        merge_capture_into_union(union, [row("Pedro Mendes", "1 +", "2.95", "cap_9"),
                                         row("Sekou Koita", "1 +", "3.00", "cap_9")], "Strzelcy")
        self.assertEqual(len(core._select_stable_tab_snapshot(union, 2)), 2)

    def test_strzelcy_retry_never_extends_raw_union(self):
        source = inspect.getsource(core)
        self.assertNotIn("dom_data.extend(_extract_dom_from_page(page, tab_name))", source)
        self.assertIn("merge_capture_into_union(dom_data, _extract_dom_from_page(page, tab_name), tab_name)", source)


if __name__ == "__main__":
    unittest.main()
