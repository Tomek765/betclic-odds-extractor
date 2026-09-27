"""Regression: market section context is bound structurally, not by DOM order.

Real Betclic tabs render ``h2.marketBox_categoryTitle[data-section]`` headings
as flat siblings of the markets they introduce inside one
``.verticalScroller_list``; each market element carries the same
``data-section``.  The legacy extractor walked the button's ancestors and took
``ancestor.querySelector(<any section heading>)``.  At the list level that is
the first heading of the whole tab, so every market inherited the first
section's title.  The parser reads that title as period, scorer-scope and
participant evidence, so a semantic-bearing first section ("Seria rzutów
karnych", "Pierwszy/ostatni strzelec", ...) rewrote the semantics of every
other market in the tab.  The immutable snapshots below are real captures
tracked in ``snapshots/``; moving one real section to the top reproduces an
event whose section order differs.
"""
import re
import unittest
from pathlib import Path

from core import _extract_dom_from_page, attach_structural_provenance, semantic_quarantine_ledger
from parser import parse_market_record

SNAPSHOTS = Path(__file__).parent / "snapshots"
WYNIK = "tab_run_1785259772_7560_2_Wynik.html"          # NK Celje - KF Egnatia Rrogozhine
STRZELCY = "tab_run_1787475817_15748_4_Strzelcy.html"   # Elche - Barcelona
STATYSTYKI = "tab_run_1787475817_15748_7_Statystyki.html"

MOVE_SECTION_FIRST = """(key) => {
  const list = document.querySelector('.verticalScroller_list');
  const members = Array.from(list.children).filter(e => e.getAttribute('data-section') === key);
  for (const e of members.reverse()) list.insertBefore(e, list.firstElementChild);
  return members.length;
}"""

SECTION_KEYS = """() => Object.fromEntries(Array.from(
  document.querySelectorAll('.marketBox_categoryTitle[data-section]'))
  .map(h => [h.getAttribute('data-section'), (h.innerText || h.textContent).replace(/\\s+/g, ' ').trim()]))"""

STATISTICS_WIDGET_DOM = """
<div class="matchStats">
  <h2 class="stats_groupTitle">Statystyki meczu - 1. połowa</h2>
  <button class="btn is-odd">Posiadanie 1.55</button>
</div>
<sports-match-markets class="block">
  <div class="verticalScroller_list">
    <sports-markets-single-market class="block marketElement">
      <div class="marketBox">
        <h2 class="marketBox_headTitle">Wynik meczu (z wyłączeniem dogrywki)</h2>
        <div class="marketBox_body">
          <div class="marketBox_lineSelection"><button class="btn is-odd">Home FC 2.10</button></div>
          <div class="marketBox_lineSelection"><button class="btn is-odd">Remis 3.30</button></div>
          <div class="marketBox_lineSelection"><button class="btn is-odd">Away FC 3.60</button></div>
        </div>
      </div>
    </sports-markets-single-market>
  </div>
</sports-match-markets>
<sports-betting-slip>
  <div class="progressiveBettingSlip_cardContent">
    <betting-slip-odds-field><div class="btnWrapper">
      <button class="is-naked btn is-large is-odd is-readonly">1,93</button>
    </div></betting-slip-odds-field>
  </div>
</sports-betting-slip>
"""


def _teams(name: str) -> tuple[str, str]:
    html = (SNAPSHOTS / name).read_text(encoding="utf-8", errors="replace")
    match = re.search(r"<title>Obstawianie (.+?) - (.+?) \|", html)
    return match.group(1), match.group(2)


def _parse(row: dict, tab: str, home: str, away: str) -> dict:
    record, _ = parse_market_record(
        category=tab, market_title=row["market"], raw_selection=row["selection"],
        odds_str=row["odds"], raw_text=row["raw"], section_title=row["section_title"],
        ancestor_title=row["ancestor_title"], period_hint=row["period_hint"], main_tab=tab,
        settlement_scope_hint=row["settlement_scope_hint"], line_hint=row["line_hint"],
        participant_hint=row["participant_hint"], handicap_kind_hint=row["handicap_kind"],
        market_instance_id=row["market_instance_id"], home_team=home, away_team=away,
        container_id=row["container_id"],
    )
    return record


def _offer_key(row: dict) -> tuple:
    # DOM paths change when sections are reordered; the displayed offer does not.
    return (row["market"], row["raw"], row["odds"], row["period_hint"], row["participant_hint"])


class SectionContextBinding(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright

        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)
        cls.page = cls.browser.new_page()
        # Saved snapshots reference remote assets; replay stays offline.
        cls.page.route("**/*", lambda route: route.abort()
                       if route.request.url.startswith("http") else route.continue_())

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def _extract(self, name: str, tab: str, first_section: str | None = None):
        html = (SNAPSHOTS / name).read_text(encoding="utf-8", errors="replace")
        self.page.set_content(html, wait_until="domcontentloaded")
        if first_section:
            self.assertGreater(self.page.evaluate(MOVE_SECTION_FIRST, first_section), 0)
        return _extract_dom_from_page(self.page, tab), self.page.evaluate(SECTION_KEYS)

    def _semantics(self, rows, tab, name):
        home, away = _teams(name)
        fields = ("FAMILY", "PERIOD", "OWNER", "PARTICIPANT", "SELECTION", "LINE",
                  "SETTLEMENT", "SCORER_SCOPE")
        out: dict[tuple, list] = {}
        for row in rows:
            if not row["market"]:
                continue
            record = _parse(row, tab, home, away)
            if record:
                out.setdefault(_offer_key(row), []).append(tuple(record.get(f) for f in fields))
        return {key: sorted(values) for key, values in out.items()}

    def test_every_market_gets_its_own_data_section_heading(self):
        for name, tab in ((WYNIK, "Wynik"), (STRZELCY, "Strzelcy"), (STATYSTYKI, "Statystyki")):
            rows, headings = self._extract(name, tab)
            keyed = [row for row in rows if row["section_key"]]
            self.assertTrue(keyed, name)
            for row in keyed:
                expected = headings[row["section_key"]]
                if expected == row["market"]:
                    self.assertEqual((row["ancestor_title"], row["section_source"]),
                                     ("", "SECTION_HEADER_EQUALS_MARKET_TITLE"), name)
                else:
                    self.assertEqual((row["ancestor_title"], row["section_source"]),
                                     (expected, "DATA_SECTION_HEADER"), (name, row["market"]))

    def test_statistics_sections_do_not_inherit_first_statistics_heading(self):
        rows, _ = self._extract(STATYSTYKI, "Statystyki")
        cards = {row["ancestor_title"] for row in rows if row["section_key"] == "subca_ftb_crd"}
        # BEFORE: {"Rzuty rożne"} - the tab's first section leaked into cards markets.
        self.assertEqual(cards, {"Kartki"})
        self.assertEqual(len({row["ancestor_title"] for row in rows} - {""}), 8)

    def test_penalty_shootout_first_section_does_not_rewrite_main_market_periods(self):
        baseline, _ = self._extract(WYNIK, "Wynik")
        moved, _ = self._extract(WYNIK, "Wynik", first_section="subca_ftb_pes")
        home, away = _teams(WYNIK)
        main = [row for row in moved if row["market"] == "Wynik meczu (z wyłączeniem dogrywki)"]
        self.assertEqual(len(main), 3)
        for row in main:
            self.assertEqual(row["ancestor_title"], "Wynik - popularne")
            self.assertEqual(_parse(row, "Wynik", home, away)["PERIOD"], "FULL_TIME")
            # BEFORE: the legacy walk bound this market to the tab's first heading.
            leaked = _parse({**row, "section_title": "Seria rzutów karnych",
                             "ancestor_title": "Seria rzutów karnych"}, "Wynik", home, away)
            self.assertEqual(leaked["PERIOD"], "OTHER")
        self.assertEqual(self._semantics(moved, "Wynik", WYNIK),
                         self._semantics(baseline, "Wynik", WYNIK))

    def test_first_last_scorer_section_does_not_rescope_anytime_markets(self):
        baseline, _ = self._extract(STRZELCY, "Strzelcy")
        moved, _ = self._extract(STRZELCY, "Strzelcy", first_section="subca_ftb_flg")
        home, away = _teams(STRZELCY)
        scorer = [row for row in moved if row["market"] == "Strzelec"]
        self.assertTrue(scorer)
        scopes = {_parse(row, "Strzelcy", home, away)["SCORER_SCOPE"] for row in scorer}
        self.assertIn("ANYTIME", scopes)
        self.assertFalse(scopes & {"FIRST_GOAL", "LAST_GOAL"})
        # BEFORE: the leaked first heading rescoped these accepted rows to the
        # last goal - a silent false accept, not a quarantine.
        leaked = {_parse({**row, "section_title": "Pierwszy/ostatni strzelec",
                          "ancestor_title": "Pierwszy/ostatni strzelec"}, "Strzelcy", home, away)["SCORER_SCOPE"]
                  for row in scorer}
        self.assertEqual(leaked, {"LAST_GOAL"})
        self.assertEqual(self._semantics(moved, "Strzelcy", STRZELCY),
                         self._semantics(baseline, "Strzelcy", STRZELCY))

    def test_every_real_section_order_yields_identical_context_and_semantics(self):
        for name, tab in ((WYNIK, "Wynik"), (STRZELCY, "Strzelcy"), (STATYSTYKI, "Statystyki")):
            baseline, headings = self._extract(name, tab)
            expected_context = sorted((_offer_key(r), r["ancestor_title"], r["section_title"]) for r in baseline)
            expected_semantics = self._semantics(baseline, tab, name)
            for key in list(headings)[1:]:
                moved, _ = self._extract(name, tab, first_section=key)
                with self.subTest(snapshot=name, first_section=key):
                    self.assertEqual(sorted((_offer_key(r), r["ancestor_title"], r["section_title"]) for r in moved),
                                     expected_context)
                    self.assertEqual(self._semantics(moved, tab, name), expected_semantics)

    def test_page_statistics_widget_and_bet_slip_are_outside_market_pipeline(self):
        self.page.set_content(STATISTICS_WIDGET_DOM)
        rows = _extract_dom_from_page(self.page, "Top")
        # The widget control has no market container and stays an explicit
        # headerless observation; the bet slip's readonly copy is not captured.
        self.assertEqual(sorted(row["raw"] for row in rows),
                         ["Away FC 3.60", "Home FC 2.10", "Posiadanie 1.55", "Remis 3.30"])
        self.assertFalse([row for row in rows if "betting-slip" in row["dom_path"]])
        market = [row for row in rows if row["market"]]
        self.assertEqual(len(market), 3)
        for row in market:
            # BEFORE: "Statystyki meczu - 1. połowa" leaked in and forced 1ST_HALF.
            self.assertEqual((row["ancestor_title"], row["section_title"], row["section_source"]),
                             ("", "", "NONE"))
            record = _parse(row, "Top", "Home FC", "Away FC")
            self.assertEqual((record["FAMILY"], record["PERIOD"]), ("1X2", "FULL_TIME"))
        widget = next(row for row in rows if not row["market"])
        self.assertTrue(widget["missing_header"])

    def test_section_provenance_reaches_record_and_quarantine_ledger(self):
        record = {"FAMILY": "PLAYER_PROP", "MARKET": "Strzelec - Xtra Wygrana", "CATEGORY": "Strzelcy",
                  "SELECTION": "Fer Nino", "SECTION_PATH": "Strzelec > Strzelec - Xtra Wygrana"}
        attach_structural_provenance(record, {"section_source": "DATA_SECTION_HEADER", "section_key": "subca_ftb_bgs"})
        self.assertEqual((record["SECTION_SOURCE"], record["SECTION_KEY"]), ("DATA_SECTION_HEADER", "subca_ftb_bgs"))
        ledger = semantic_quarantine_ledger([record])
        self.assertEqual(ledger[0]["reason"], "UNCONFIRMED_XTRA_PAYOUT_CONTRACT")
        self.assertEqual(ledger[0]["section_source"], "DATA_SECTION_HEADER")
        self.assertEqual(ledger[0]["section_path"], "Strzelec > Strzelec - Xtra Wygrana")


if __name__ == "__main__":
    unittest.main()
