"""Live 2026-10-01, Bosnia and Herzegovina - Sweden: the Strzelcy tab was empty.

Betclic rendered the tab lazily; three quick empty passes ended the crawl after
0.8 s with zero rows, the tab was reported PASS/EMPTY_TAB and the self-test
said PASS while every scorer market of the tab (126-356 bets in earlier
matches) was missing.
"""
import time
import unittest
from unittest import mock

import exhaustive
from exhaustive import ExhaustiveStateCrawler


class _StaticPage:
    """No controls, no scroll containers: only the capture function matters."""
    def evaluate(self, *_args, **_kwargs):
        return {"controls": [], "scrolls": []}


def _delayed_capture(delay):
    started = time.time()
    row = {"native_selection_id": "sel-1", "market": "Strzelec", "selection": "Edin Dzeko",
           "odds": "2.10", "raw": "Edin Dzeko 2.10"}

    def capture(_page, _tab):
        return [dict(row)] if time.time() - started >= delay else []
    return capture


class EmptyTabWaitsForContent(unittest.TestCase):
    def crawl(self, tab, capture, grace=3.0):
        with mock.patch.object(exhaustive, "EMPTY_TAB_GRACE_SECONDS", grace):
            crawler = ExhaustiveStateCrawler(_StaticPage(), capture, time.time() + 20)
            started = time.time()
            rows, manifest = crawler.crawl_tab(tab)
        return rows, manifest, time.time() - started

    def test_lazily_rendered_tab_is_captured(self):
        rows, manifest, _ = self.crawl("Strzelcy", _delayed_capture(1.2))
        self.assertEqual([row["selection"] for row in rows], ["Edin Dzeko"])
        self.assertGreaterEqual(manifest.stabilization_passes, 3)

    def test_truly_empty_tab_ends_after_the_grace_period(self):
        rows, _, seconds = self.crawl("Strzelcy", lambda *_: [], grace=1.0)
        self.assertEqual(rows, [])
        self.assertGreaterEqual(seconds, 1.0)
        self.assertLess(seconds, 5.0)

    def test_mycombi_is_not_delayed(self):
        _, _, seconds = self.crawl("MyCombi", lambda *_: [], grace=5.0)
        self.assertLess(seconds, 2.0)


if __name__ == "__main__":
    unittest.main()
