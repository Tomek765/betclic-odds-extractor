"""A tab is complete only when no new selection appeared for QUIET_SECONDS.

Three quick identical passes (~0.3 s) could end a tab while Betclic was still
rendering rows (lazy lists, rows revealed by an expander or a scroll).  A price
tick is not a new selection: it must neither keep the crawl alive forever nor
leave a stale price behind.
"""
import time
import unittest
from unittest import mock

import exhaustive
from exhaustive import ExhaustiveStateCrawler, selection_identity


class _StaticPage:
    def evaluate(self, *_args, **_kwargs):
        return {"controls": [], "scrolls": []}


def _row(name, odds, native=None):
    row = {"market": "Strzelec", "selection": name, "odds": odds, "raw": f"{name} {odds}",
           "market_instance_id": "tab:Strzelcy|box#1"}
    if native:
        row["native_selection_id"] = native
    return row


def crawl(capture, quiet=1.0, deadline=15.0):
    with mock.patch.object(exhaustive, "QUIET_SECONDS", quiet):
        crawler = ExhaustiveStateCrawler(_StaticPage(), capture, time.time() + deadline)
        started = time.time()
        rows, manifest = crawler.crawl_tab("Strzelcy")
    return rows, manifest, time.time() - started


class QuietTimeStability(unittest.TestCase):
    def test_rows_rendered_late_are_captured(self):
        started = time.time()

        def capture(_page, _tab):
            rows = [_row("Gracz A", "2.10")]
            if time.time() - started >= 0.7:  # the rest of the list renders later
                rows += [_row("Gracz B", "3.40"), _row("Gracz C", "5.00")]
            return rows
        rows, manifest, _ = crawl(capture)
        self.assertEqual(sorted(row["selection"] for row in rows), ["Gracz A", "Gracz B", "Gracz C"])
        self.assertEqual(manifest.stabilization_passes, 3)

    def test_a_ticking_price_does_not_block_completion(self):
        def capture(_page, _tab):
            # A new price on every pass: same selection, different odds.
            return [_row("Gracz A", f"{2 + (time.time() * 10 % 10) / 100:.2f}", native="sel-a")]
        rows, manifest, seconds = crawl(capture, quiet=0.8)
        self.assertEqual(manifest.stabilization_passes, 3)
        self.assertLess(seconds, 5.0)
        self.assertEqual(len(rows), 1)

    def test_latest_price_of_a_native_selection_wins(self):
        prices = iter(["2.10", "2.10", "2.25"])
        last = {"odds": "2.10"}

        def capture(_page, _tab):
            last["odds"] = next(prices, last["odds"])
            return [_row("Gracz A", last["odds"], native="sel-a")]
        rows, _, _ = crawl(capture, quiet=0.5)
        self.assertEqual([row["odds"] for row in rows], ["2.25"])

    def test_identity_ignores_only_the_price(self):
        self.assertEqual(selection_identity(_row("Gracz A", "2.10")), selection_identity(_row("Gracz A", "2.30")))
        self.assertNotEqual(selection_identity(_row("Gracz A", "2.10")), selection_identity(_row("Gracz B", "2.10")))


if __name__ == "__main__":
    unittest.main()
