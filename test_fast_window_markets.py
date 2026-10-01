"""Live 2026-10-01, Borussia Dortmund - Werder: Fast cards are minute-window markets.

The "⚡ Fast" card "Zawodnik strzeli" (header "00:00 - 14:59 Edytuj") was
also shown in the Top and Strzelcy tabs and was exported as a full-match
anytime scorer (Guirassy 13, while his real anytime price is ~1.5).
"""
import unittest

from core import (
    _dedupe_records_preserving_order,
    _semantic_quarantine_reason,
    canonical_export_boundary,
    partition_semantic_records,
)
from parser import has_selectable_time_window, is_fast_window_tab

FAST_BOX = ("Zawodnik strzeli 00:00 - 14:59 Edytuj Borussia Dortmund Serhou Guirassy 13 "
            "Mathis Albert 16,75 Werder Cedric Itten 30")


def scorer(category, raw_ids, box="", odds="13", selection="Serhou Guirassy"):
    return {
        "CATEGORY": category, "FAMILY": "GOALSCORER", "MARKET": "Zawodnik strzeli", "PERIOD": "FULL_TIME",
        "OWNER": "Borussia Dortmund", "SELECTION": selection, "LINE": "", "SETTLEMENT": "WIN_LOSE",
        "ODDS": odds, "RAW": f"{selection} {odds}", "SCORER_SCOPE": "ANYTIME", "PARTICIPANT": selection,
        "PARTICIPANTS": [selection], "BOX_CONTEXT": box, "raw_record_id": raw_ids[0],
        "source_raw_record_ids": list(raw_ids),
    }


class WindowEvidence(unittest.TestCase):
    def test_editable_window_header_is_detected(self):
        self.assertTrue(has_selectable_time_window(FAST_BOX))
        self.assertTrue(has_selectable_time_window("Gole 00:00 - 14:59 Edytuj Powyżej 0,5 2,45"))
        self.assertTrue(has_selectable_time_window("Wynik 15:00 - 29:59 Edytuj Borussia Dortmund 3,58"))

    def test_first_goal_time_selections_are_not_a_window_market(self):
        self.assertFalse(has_selectable_time_window(
            "Czas 1. gola 00:00 - 09:59 3,10 10:00 - 19:59 3,68 20:00 - 29:59 4,95"))
        self.assertFalse(has_selectable_time_window("Strzelec Borussia Dortmund Serhou Guirassy 1,62"))

    def test_fast_tab(self):
        self.assertTrue(is_fast_window_tab("⚡ Fast"))
        self.assertFalse(is_fast_window_tab("Strzelcy"))
        self.assertFalse(is_fast_window_tab("Breakfast"))


class FastCardsNeverBecomeFullMatch(unittest.TestCase):
    def test_card_with_window_in_any_tab_is_quarantined(self):
        self.assertEqual(_semantic_quarantine_reason(scorer("Strzelcy", ["r:517"], FAST_BOX)),
                         "UNCONFIRMED_PLAYER_PROP_PERIOD")

    def test_fast_tab_without_box_text_is_quarantined(self):
        self.assertEqual(_semantic_quarantine_reason(scorer("⚡ Fast", ["r:129"])),
                         "UNCONFIRMED_PLAYER_PROP_PERIOD")

    def test_match_market_window_card_uses_market_period_reason(self):
        row = {"CATEGORY": "Top", "FAMILY": "GOALS_OU", "MARKET": "Gole", "PERIOD": "FULL_TIME",
               "SELECTION": "OVER", "LINE": "0.5", "SETTLEMENT": "NO_PUSH", "ODDS": "2.45",
               "BOX_CONTEXT": "Gole 00:00 - 14:59 Edytuj Powyżej 0,5 2,45 Poniżej 0,5 1,45"}
        self.assertEqual(_semantic_quarantine_reason(row), "UNCONFIRMED_MARKET_PERIOD")

    def test_copy_without_window_text_is_linked_by_shared_source_records(self):
        fast = scorer("⚡ Fast", ["r:120", "r:129", "r:517"], FAST_BOX)
        strzelcy = scorer("Strzelcy", ["r:120", "r:129", "r:517"])
        accepted, quarantined = partition_semantic_records([strzelcy, fast])
        self.assertEqual(accepted, [])
        self.assertEqual(len(quarantined), 2)

    def test_real_full_match_scorer_is_still_accepted(self):
        real = scorer("Strzelcy", ["r:300"], "Strzelec Borussia Dortmund Serhou Guirassy 1,62", odds="1.62")
        fast = scorer("⚡ Fast", ["r:129"], FAST_BOX)
        accepted, quarantined = partition_semantic_records([real, fast])
        self.assertEqual([row["ODDS"] for row in accepted], ["1.62"])
        self.assertEqual([row["ODDS"] for row in quarantined], ["13"])

    def test_merge_keeps_window_flag_when_window_copy_is_absorbed(self):
        top = scorer("Top", ["r:120"])
        fast = scorer("⚡ Fast", ["r:129"], FAST_BOX)
        for row in (top, fast):
            row["PERIOD_SCOPE_ID"] = "scope-1"
        unique, _ = _dedupe_records_preserving_order([top, fast], [])
        accepted, quarantined = partition_semantic_records(unique)
        self.assertEqual(accepted, [])
        self.assertTrue(quarantined)

    def test_production_canonical_boundary(self):
        rows = [scorer("⚡ Fast", ["r:120", "r:129", "r:517"], FAST_BOX),
                scorer("Strzelcy", ["r:120", "r:129", "r:517"]),
                scorer("Strzelcy", ["r:300"], "Strzelec Borussia Dortmund Serhou Guirassy 1,62", odds="1.62")]
        _, accepted, quarantined, _, _ = canonical_export_boundary(rows, "Borussia Dortmund", "Werder")
        self.assertEqual({row["ODDS"] for row in accepted}, {"1.62"})
        self.assertEqual({row["ODDS"] for row in quarantined}, {"13"})


if __name__ == "__main__":
    unittest.main()
