"""Live 2026-10-25 (Hibernian - Celtic): Betclic's new market markup failed the capture.

* An opened market gains the class "is-expanded" on its body, so the same
  price button had two identities (before/after opening): 333 reads for 270
  buttons in Wynik and TAB_STATUS_FAIL (LEDGER_CONSERVATION_GAP).
* Betclic now marks an opened expander with aria-expanded="true" (the arrow
  icon no longer turns up), so every expander looked closed.
* Player-market expanders rendered after the last crawl pass were counted as
  unexpanded although player markets stay at their default view by policy.
* A price moved during the scan (one hour before kick-off) left the old price
  as a second read of the same button.

Replaying the eight saved tab pages of that run through the crawler now gives
PASS on every tab, with reads equal to the price buttons on the page.
"""
import time
import unittest
from unittest import mock

import core
import exhaustive
from exhaustive import CoverageManifest, ExhaustiveStateCrawler

BODY = ('<div class="marketBox_container is-active"><div class="verticalScroller_list">'
        '<sports-markets-single-market class="marketElement"><div class="marketBox">'
        '<h2 class="marketBox_headTitle">Wynik i gole</h2>'
        '<div class="marketBox_body is-expandable{state}"><div class="marketBox_lineSelection">'
        '<span class="marketBox_label">Hibernian &amp; Powyżej 1,5</span>'
        '<button class="btn is-odd"><span class="oddValue">4,50</span></button></div></div>'
        '{button}</div></sports-markets-single-market></div></div>')
SEE_MORE = ('<button class="btn is-ghost is-tertiary is-small is-seeMore{cls}"{aria}>'
            '<span class="icons icon_utilityArrowDownDefault"></span></button>')


class _Browser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
            cls._pw = sync_playwright().start()
            cls._browser = cls._pw.chromium.launch()
        except Exception as exc:
            raise unittest.SkipTest(f"Chromium unavailable: {exc}")
        cls.page = cls._browser.new_page()

    @classmethod
    def tearDownClass(cls):
        cls._browser.close()
        cls._pw.stop()


class ExpansionStateIsNotIdentity(_Browser):
    def capture(self, state):
        self.page.set_content(BODY.format(state=state, button=""))
        rows = self.page.evaluate(core._make_dom_script(), "Wynik")
        self.assertEqual(len(rows), 1)
        return rows[0]

    def test_same_button_before_and_after_opening_has_one_identity(self):
        closed, opened = self.capture(""), self.capture(" is-expanded")
        for key in ("market_instance_id", "dom_path", "period_scope_id"):
            self.assertEqual(closed[key], opened[key], key)
        self.assertEqual(exhaustive.selection_identity(closed), exhaustive.selection_identity(opened))


class ExpanderStateFromAria(_Browser):
    def expanded(self, cls, aria):
        self.page.set_content(BODY.format(state="", button=SEE_MORE.format(cls=cls, aria=aria)))
        controls = [c for c in self.page.evaluate(ExhaustiveStateCrawler._script())["controls"] if c.get("see_more")]
        self.assertEqual(len(controls), 1)
        return controls[0]["expanded"]

    def test_betclic_2026_10_expander_states(self):
        self.assertEqual(self.expanded(" is-expanded", ' aria-expanded="true"'), "true")
        self.assertEqual(self.expanded("", ' aria-expanded="false"'), "false")
        self.assertEqual(self.expanded(" is-expanded", ""), "true")
        self.assertEqual(self.expanded("", ""), "false")


class TabClosedCountFollowsPolicy(_Browser):
    """Live 2026-10-25 (FC Thun - Lugano, FAST10): the tab status counted every
    aria-expanded="false" button, including player-market expanders left at
    their default view by policy, so three tabs read PARTIAL."""

    def closed(self, title):
        self.page.set_content(BODY.replace("Wynik i gole", title).format(
            state="", button=SEE_MORE.format(cls="", aria=' aria-expanded="false"')))
        return core._get_dom_expansion_metrics(self.page, "Strzelcy")["remaining_closed"]

    def test_player_market_at_default_view_is_not_closed(self):
        self.assertEqual(self.closed("Zawodnik strzeli gola lub zaliczy asystę"), 0)

    def test_closed_match_market_still_counts(self):
        self.assertEqual(self.closed("Wynik i gole"), 1)


class LatePlayerExpandersFollowPolicy(unittest.TestCase):
    def control(self, title):
        return {"see_more": True, "expanded": "false", "semantic_path": f"{title}#7", "odds_in_box": 18,
                "role": "", "text": "expander", "aria_controls": "", "local_index": 0}

    def test_player_market_first_seen_in_the_final_snapshot_is_resolved(self):
        manifest = CoverageManifest("Strzelcy")
        self.assertTrue(ExhaustiveStateCrawler._see_more_resolved(
            self.control("Zawodnik strzeli gola lub zaliczy asystę"), "Strzelcy", manifest))
        self.assertEqual(len(manifest.see_more_skipped), 1)

    def test_unvisited_match_market_stays_unresolved(self):
        self.assertFalse(ExhaustiveStateCrawler._see_more_resolved(
            self.control("Wynik i gole"), "Wynik", CoverageManifest("Wynik")))


class PriceMovedDuringScan(unittest.TestCase):
    def test_one_button_is_one_read_with_the_latest_price(self):
        prices = iter(["1.95", "1.95", "1.90"])

        def capture(_page, _tab):
            price = next(prices, "1.90")
            return [{"market": "Spalone 1X2 (OPTA) (z dogrywką)", "selection": "Hibernian", "odds": price,
                     "raw": f"Hibernian {price}", "market_instance_id": "tab:Statystyki|box#4|row#0|cell:b0"}]

        class Page:
            def evaluate(self, *_a, **_k):
                return {"controls": [], "scrolls": []}

        with mock.patch.object(exhaustive, "QUIET_SECONDS", 0.3):
            rows, manifest = ExhaustiveStateCrawler(Page(), capture, time.time() + 10).crawl_tab("Statystyki")
        self.assertEqual([(r["selection"], r["odds"]) for r in rows], [("Hibernian", "1.90")])
        self.assertEqual(len(manifest.unique_visible_signatures), len(manifest.raw_exported_signatures))


if __name__ == "__main__":
    unittest.main()
