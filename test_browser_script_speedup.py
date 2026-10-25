"""Audit 2026-10-25: faster browser scripts must read exactly what FAST7 read.

The crawler snapshot tested every page element with a nested button search
(quadratic in page size) and the price capture recomputed whole-market texts,
the market index and ancestor paths for every price button.  The optimised
scripts compute these once per element.  The fixture holds the FAST7 scripts'
output on two Betclic-shaped pages; the current scripts must reproduce it.
"""
import json
import unittest
from pathlib import Path

import core
from exhaustive import ExhaustiveStateCrawler

GOLDEN = json.loads((Path(__file__).parent / "tests_context/fixtures/browser_scripts_golden_fast7.json")
                    .read_text(encoding="utf-8"))


class BrowserScriptsMatchGolden(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
            cls._pw = sync_playwright().start()
            cls._browser = cls._pw.chromium.launch()
        except Exception as exc:  # no bundled/installed Chromium in this environment
            raise unittest.SkipTest(f"Chromium unavailable: {exc}")
        cls.page = cls._browser.new_page(viewport={"width": 1400, "height": 900})

    @classmethod
    def tearDownClass(cls):
        cls._browser.close()
        cls._pw.stop()

    def test_price_capture_is_identical(self):
        self.page.set_content(GOLDEN["dom_html"])
        self.assertEqual(self.page.evaluate(core._make_dom_script(), "Strzelcy"), GOLDEN["dom"])

    def test_crawler_snapshot_is_identical(self):
        self.page.set_content(GOLDEN["snapshot_html"])
        self.assertEqual(self.page.evaluate(ExhaustiveStateCrawler._script()), GOLDEN["snapshot"])


if __name__ == "__main__":
    unittest.main()
