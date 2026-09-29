"""Regression: icon-only "see more" expanders of multi-line Betclic markets.

Live audit (2026-09-29, four consecutive real matches): every grid market such
as "Wynik meczu & oba zespoły strzelą", "Wynik Meczu Połowa / Cały", "Różnica
goli" or "Wynik i kto zdobędzie 1. bramkę" exported exactly 3 selections.  The
DOM shows why: Betclic renders 3 lines and a text-less
``button.is-seeMore`` (arrow icon) that reveals the rest.  The crawler skipped
every control without visible text, and ``remaining_more`` only counted
text-bearing controls, so roughly half of the bets were lost without any
warning.
"""
import time
import unittest

from core import _extract_dom_from_page
from exhaustive import ExhaustiveStateCrawler

MARKET = """
<sports-markets-single-market class="block marketElement" data-t="{t}">
 <div class="marketBox">
  <div class="marketBox_head"><h2 class="marketBox_headTitle"><span>{title}</span></h2></div>
  <sports-matrix-markets>
   <div class="marketBox_body" id="body-{t}">{lines}</div>
   {button}
  </sports-matrix-markets>
 </div>
</sports-markets-single-market>
"""
LINE = ('<div class="marketBox_lineSelection"><p class="marketBox_label">{label}</p>'
        '<button class="btn is-large is-odd"><span class="btn_label">{odds}</span></button></div>')


def market(t, title, first, rest, behaviour="expands"):
    lines = "".join(LINE.format(label=l, odds=o) for l, o in first)
    extra = "".join(LINE.format(label=l, odds=o) for l, o in rest).replace("'", "\\'").replace('"', "&quot;")
    if not rest:
        button = ""
    else:
        handler = {
            # reveals the rest and flips the icon, like Betclic
            "expands": (f"document.getElementById('body-{t}').insertAdjacentHTML('beforeend','{extra}');"
                        "this.firstElementChild.className='icons icon_arrowUpDefault';"),
            # reveals the rest but keeps the arrow-down icon
            "no_flip": f"document.getElementById('body-{t}').insertAdjacentHTML('beforeend','{extra}');",
            # a broken expander that reveals nothing
            "dead": "",
        }[behaviour]
        button = (f'<div class="btnWrapper"><button class="btn is-medium is-seeMore is-tertiary" '
                  f'onclick="{handler}"><span class="icons icon_arrowDownDefault"></span></button></div>')
    return MARKET.format(t=t, title=title, lines=lines, button=button)


def page_html(*markets):
    return "<html><body><div class='verticalScroller_list'>" + "".join(markets) + "</div></body></html>"


GRID = market(
    "grid", "Wynik meczu & oba zespoły strzelą",
    [("Walia / Tak", "9,00"), ("Walia / Nie", "11,25"), ("Remis / Tak", "5,25")],
    [("Remis / Nie", "18,50"), ("Norwegia / Tak", "2,10"), ("Norwegia / Nie", "3,40")])
MARGIN = market(
    "margin", "Różnica goli",
    [("Walia przewagą 1 gola", "7,75"), ("Walia przewagą 2 goli", "20"), ("Walia przewagą 3 lub więcej goli", "55")],
    [("Norwegia przewagą 1 gola", "3,10"), ("Norwegia przewagą 2 goli", "3,90"), ("Norwegia przewagą 3 lub więcej goli", "4,60")])
SAME_TITLE_A = market("a", "Podwójna szansa", [("1X", "2,53"), ("12", "1,18"), ("X2", "1,14")], [])
PLAIN = market("plain", "Oba zespoły strzelą gola", [("Tak", "1,70"), ("Nie", "2,07")], [])


def labels(records, market_title):
    return sorted(r["selection"] for r in records if r["market"] == market_title)


class SeeMoreExpanderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
            cls.playwright = sync_playwright().start()
            cls.browser = cls.playwright.chromium.launch(headless=True)
        except Exception as exc:  # pragma: no cover - environment without a browser
            raise unittest.SkipTest(f"Chromium unavailable: {exc}")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def crawl(self, html):
        page = self.browser.new_page()
        try:
            page.set_content(html, wait_until="domcontentloaded")
            crawler = ExhaustiveStateCrawler(page, _extract_dom_from_page, time.time() + 30)
            return crawler.crawl_tab("Wynik")
        finally:
            page.close()

    def test_collapsed_grid_markets_are_fully_captured(self):
        records, manifest = self.crawl(page_html(GRID, MARGIN, PLAIN))
        self.assertEqual(len(labels(records, "Wynik meczu & oba zespoły strzelą")), 6)
        self.assertEqual(len(labels(records, "Różnica goli")), 6)
        self.assertIn("Norwegia / Nie", labels(records, "Wynik meczu & oba zespoły strzelą"))
        self.assertIn("Norwegia przewagą 3 lub więcej goli", labels(records, "Różnica goli"))
        self.assertEqual(len(labels(records, "Oba zespoły strzelą gola")), 2)
        self.assertEqual((manifest.remaining_closed, manifest.remaining_more), (0, 0))
        self.assertEqual(manifest.expanded_controls, 2)

    def test_each_expander_is_clicked_exactly_once(self):
        # Clicking twice would collapse a real toggle and lose the revealed bets.
        records, manifest = self.crawl(page_html(GRID, GRID.replace("grid", "grid2")))
        self.assertEqual(manifest.expanded_controls, 2)
        self.assertEqual(len(labels(records, "Wynik meczu & oba zespoły strzelą")), 12)

    def test_many_expanders_are_opened_in_one_pass_with_correct_targets(self):
        markets = [GRID.replace("grid", f"g{i}").replace("Wynik meczu & oba zespoły strzelą", f"Rynek {i}")
                   for i in range(8)]
        captures = []

        def counting_capture(page, tab):
            captures.append(1)
            return _extract_dom_from_page(page, tab)

        page = self.browser.new_page()
        try:
            page.set_content(page_html(*markets), wait_until="domcontentloaded")
            records, manifest = ExhaustiveStateCrawler(page, counting_capture, time.time() + 30).crawl_tab("Wynik")
        finally:
            page.close()
        for i in range(8):
            self.assertEqual(len(labels(records, f"Rynek {i}")), 6, i)
        self.assertEqual((manifest.expanded_controls, manifest.remaining_closed), (8, 0))
        # one-by-one opening would need 8 extra captures on top of the 3 stability passes
        self.assertLessEqual(len(captures), 6)

    def test_expander_that_keeps_its_arrow_is_still_resolved_by_new_bets(self):
        html = page_html(market("nf", "Różnica goli", [("A", "2,00"), ("B", "3,00"), ("C", "4,00")],
                                [("D", "5,00"), ("E", "6,00"), ("F", "7,00")], behaviour="no_flip"))
        records, manifest = self.crawl(html)
        self.assertEqual(len(labels(records, "Różnica goli")), 6)
        self.assertEqual(manifest.remaining_closed, 0)

    def test_expander_that_reveals_nothing_fails_closed(self):
        html = page_html(market("dead", "Różnica goli", [("A", "2,00"), ("B", "3,00"), ("C", "4,00")],
                                [("D", "5,00")], behaviour="dead"))
        records, manifest = self.crawl(html)
        self.assertEqual(len(labels(records, "Różnica goli")), 3)
        self.assertGreater(manifest.remaining_closed, 0)

    def test_pages_without_expanders_are_unaffected(self):
        records, manifest = self.crawl(page_html(PLAIN, SAME_TITLE_A))
        self.assertEqual(len(records), 5)
        self.assertEqual((manifest.expanded_controls, manifest.remaining_closed, manifest.remaining_more), (0, 0, 0))


class NewlyVisibleSelectionsStayCorrect(unittest.TestCase):
    """Bets revealed by the expander must classify correctly or fail closed."""

    def test_crawled_records_parse_to_all_six_distinct_outcomes(self):
        from parser import parse_market_record
        crawl = SeeMoreExpanderTest.crawl
        test = SeeMoreExpanderTest("test_collapsed_grid_markets_are_fully_captured")
        SeeMoreExpanderTest.setUpClass()
        try:
            records, _ = crawl(test, page_html(GRID, MARGIN))
        finally:
            SeeMoreExpanderTest.tearDownClass()
        parsed = {}
        for record in records:
            row, issue = parse_market_record(
                category="Wynik", market_title=record["market"], raw_selection=record["selection"],
                odds_str=record["odds"].replace(",", "."), raw_text=record["raw"], section_title="",
                home_team="Walia", away_team="Norwegia", container_id="c")
            self.assertIsNone(issue, record)
            parsed.setdefault(row["MARKET"], set()).add(row["SELECTION"])
        self.assertEqual(parsed["Wynik meczu & oba zespoły strzelą"], {
            "WALIA_/_TAK", "WALIA_/_NIE", "REMIS_/_TAK", "REMIS_/_NIE", "NORWEGIA_/_TAK", "NORWEGIA_/_NIE"})
        self.assertEqual(len(parsed["Różnica goli"]), 6)

    def test_context_engine_accepts_the_added_bets_without_side_effects(self):
        from apex_context_engine.engine import build_context
        from apex_context_engine.packet_parser import parse_packet_text
        from test_package_context_quarantine import odd, with_odds
        base = [odd(FAMILY="COMPOUND_LOGIC", MARKET="Wynik meczu & oba zespoły strzelą", SELECTION=sel,
                    SETTLEMENT="WIN_LOSE", ODDS=price, RAW=f"{sel} {price}")
                for sel, price in (("HOME_/_TAK", "9.00"), ("HOME_/_NIE", "11.25"), ("REMIS_/_TAK", "5.25"))]
        added = [odd(FAMILY="COMPOUND_LOGIC", MARKET="Wynik meczu & oba zespoły strzelą", SELECTION=sel,
                     SETTLEMENT="WIN_LOSE", ODDS=price, RAW=f"{sel} {price}")
                 for sel, price in (("REMIS_/_NIE", "18.50"), ("NORWEGIA_/_TAK", "2.10"), ("NORWEGIA_/_NIE", "3.40"))]
        before = build_context(parse_packet_text(with_odds(*base)))
        after = build_context(parse_packet_text(with_odds(*base, *added)))
        self.assertEqual(after.status, before.status)
        self.assertEqual(after.quarantined_rows, before.quarantined_rows)
        self.assertEqual(after.fair_markets, before.fair_markets)
        self.assertEqual(after.best_price_alerts, before.best_price_alerts)
        self.assertEqual(after.accepted_rows - before.accepted_rows, 3)


if __name__ == "__main__":
    unittest.main()
