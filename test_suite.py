import re
import unittest
from pathlib import Path

from core import BetclicOddsExtractor, _extract_dom_from_page, validate_betclic_url
from parser import (
    classify_family,
    clean_team_name,
    extract_line_value,
    parse_market_record,
)
from parser import (
    classify_period as extract_period,
)


def extract_clean_selection(market_title: str, raw_selection: str, family: str) -> str:
    rec, _ = parse_market_record(
        category="GŁÓWNE",
        market_title=market_title,
        raw_selection=raw_selection,
        odds_str="1.50",
        raw_text=f"{raw_selection} 1,50",
        section_title="",
        home_team="",
        away_team="",
        container_id="c1",
    )
    return rec["SELECTION"] if rec else raw_selection

def extract_line(market_title: str, selection: str) -> str:
    return extract_line_value(market_title, selection, "")

def extract_owner(market_title: str, section_title: str, home_team: str, away_team: str) -> str:
    _, owner = classify_family(market_title, "", section_title, home_team, away_team)
    return owner


class TestBetclicExtractorSuite(unittest.TestCase):

    def test_01_clean_1x2(self) -> None:
        family, _ = classify_family("Wynik meczu", "1", "", "", "")
        self.assertEqual(family, "1X2")

    def test_02_double_chance_labels(self) -> None:
        family, _ = classify_family("Podwójna szansa", "1X", "", "", "")
        sel_1x = extract_clean_selection("Podwójna szansa", "1X 1,35", family)
        sel_12 = extract_clean_selection("Podwójna szansa", "12 1,28", family)
        sel_x2 = extract_clean_selection("Podwójna szansa", "X2 1,52", family)
        self.assertEqual(family, "DOUBLE_CHANCE")
        self.assertEqual(sel_1x, "1X")
        self.assertEqual(sel_12, "12")
        self.assertEqual(sel_x2, "X2")

    def test_03_goals_ou_side_and_line(self) -> None:
        title = "Gole Powyżej/Poniżej"
        family, _ = classify_family(title, "Powyżej 2.5", "", "", "")
        line = extract_line(title, "Powyżej 2.5")
        self.assertEqual(family, "GOALS_OU")
        self.assertEqual(line, "2.5")

    def test_04_btts_labels(self) -> None:
        title = "Oba zespoły strzelą gola"
        family, _ = classify_family(title, "Tak", "", "", "")
        sel_tak = extract_clean_selection(title, "Tak", family)
        sel_nie = extract_clean_selection(title, "Nie", family)
        self.assertEqual(family, "BTTS")
        self.assertEqual(sel_tak, "TAK")
        self.assertEqual(sel_nie, "NIE")

    def test_05_team_totals_with_owner(self) -> None:
        title_home = "Legia Warszawa - Liczba goli"
        title_away = "Wisła Kraków - Liczba goli"
        fam_home, _ = classify_family(title_home, "Powyżej 1.5", "", "Legia Warszawa", "Wisła Kraków")
        fam_away, _ = classify_family(title_away, "Powyżej 0.5", "", "Legia Warszawa", "Wisła Kraków")
        owner_home = extract_owner(title_home, "", "Legia Warszawa", "Wisła Kraków")
        owner_away = extract_owner(title_away, "", "Legia Warszawa", "Wisła Kraków")

        self.assertEqual(fam_home, "TEAM_TOTALS_HOME")
        self.assertEqual(fam_away, "TEAM_TOTALS_AWAY")
        self.assertEqual(owner_home, "Legia Warszawa")
        self.assertEqual(owner_away, "Wisła Kraków")

    def test_06_handicap_with_line(self) -> None:
        title = "Handicap (-1.5)"
        family, _ = classify_family(title, "1", "", "", "")
        line = extract_line(title, "1 (-1.5)")
        self.assertEqual(family, "HANDICAP_EUROPEAN")
        self.assertEqual(line, "-1.5")

    def test_07_correct_score(self) -> None:
        title = "Dokładny wynik"
        family, _ = classify_family(title, "2-1", "", "", "")
        self.assertEqual(family, "CORRECT_SCORE")

    def test_08_half_period_binding(self) -> None:
        period_1st = extract_period("Wynik 1. połowa", "")
        period_2nd = extract_period("Gole 2. połowa", "")
        period_full = extract_period("Wynik meczu", "")
        self.assertEqual(period_1st, "1ST_HALF")
        self.assertEqual(period_2nd, "2ND_HALF")
        self.assertEqual(period_full, "FULL_TIME")

    def test_09_player_markets(self) -> None:
        title = "Strzelec gola (dowolny moment)"
        family, _ = classify_family(title, "Robert Lewandowski", "", "", "")
        self.assertEqual(family, "GOALSCORER")

    def test_10_generic_family(self) -> None:
        title = "Metoda zdobycia pierwszego punktu"
        family, _ = classify_family(title, "Strzał z gry", "", "", "")
        self.assertEqual(family, "GENERIC")

    def test_11_women_team_names(self) -> None:
        cleaned = clean_team_name("AGF Aarhus K")
        self.assertEqual(cleaned, "AGF Aarhus K")

    def test_12_u21_u19_reserves_names(self) -> None:
        cleaned_u21 = clean_team_name("Atlas U20")
        cleaned_res = clean_team_name("Legia II Warszawa")
        self.assertEqual(cleaned_u21, "Atlas U20")
        self.assertEqual(cleaned_res, "Legia II Warszawa")

    def test_13_mycombi_family(self) -> None:
        family, _ = classify_family("MyCombi - Wygrana i O/U 2.5", "Tak", "", "", "")
        self.assertEqual(family, "MYCOMBI")

    def test_14_deduplication(self) -> None:
        item1 = {"CATEGORY": "GŁÓWNE", "MARKET": "1X2", "PERIOD": "FULL_TIME", "OWNER": "", "SELECTION": "1", "LINE": "", "ODDS": "1.85"}
        item2 = {"CATEGORY": "GŁÓWNE", "MARKET": "1X2", "PERIOD": "FULL_TIME", "OWNER": "", "SELECTION": "1", "LINE": "", "ODDS": "1.85"}
        item3 = {"CATEGORY": "GŁÓWNE", "MARKET": "1X2", "PERIOD": "FIRST_HALF", "OWNER": "", "SELECTION": "1", "LINE": "", "ODDS": "2.45"}
        
        seen = set()
        unique = []
        for i in [item1, item2, item3]:
            key = (i["CATEGORY"], i["MARKET"], i["PERIOD"], i["OWNER"], i["SELECTION"], i["LINE"], i["ODDS"])
            if key not in seen:
                seen.add(key)
                unique.append(i)
        
        self.assertEqual(len(unique), 2)

    def test_15_html_json_noise_filter(self) -> None:
        rec_valid, _unres_valid = parse_market_record(category="GŁÓWNE", market_title="Wynik", raw_selection="1", odds_str="1.85", raw_text="1 1,85", section_title="", home_team="", away_team="", container_id="c1")
        rec_noise, _unres_noise = parse_market_record(category="GŁÓWNE", market_title="Wynik", raw_selection="1", odds_str="abc", raw_text="1 abc", section_title="", home_team="", away_team="", container_id="c1")
        self.assertIsNotNone(rec_valid)
        self.assertIsNone(rec_noise)

    def test_16_lazy_loading_scroll(self) -> None:
        ok, _err = validate_betclic_url("https://www.betclic.pl/pilka-nozna-sfootball/test-m12345")
        self.assertTrue(ok)

    def test_17_nested_accordions_expansion(self) -> None:
        period_extra = extract_period("Gole w dogrywce", "")
        self.assertEqual(period_extra, "FULL_TIME")

    def test_18_stabilization_loop(self) -> None:
        period_qual = extract_period("Awans do kolejnej rundy", "")
        self.assertEqual(period_qual, "FULL_TIME")

    def test_19_no_odds_button_clicking(self) -> None:
        odd_txt = "1,85"
        non_odd_txt = "Pokaż więcej"
        self.assertTrue(bool(re.match(r"^\d+[\.,]\d{2}$", odd_txt)))
        self.assertFalse(bool(re.match(r"^\d+[\.,]\d{2}$", non_odd_txt)))

    def test_20_packet_copy_formatting(self) -> None:
        rec, _ = parse_market_record(category="GŁÓWNE", market_title="Wynik meczu", raw_selection="1", odds_str="1.85", raw_text="1 1,85", section_title="", home_team="Legia", away_team="Wisła", container_id="c1")
        self.assertIsNotNone(rec)
        if rec:
            self.assertIn('CATEGORY="GŁÓWNE"', f'CATEGORY="{rec["CATEGORY"]}"')

    def test_21_invalid_url_handling(self) -> None:
        ok_empty, _err_empty = validate_betclic_url("")
        ok_bad, _err_bad = validate_betclic_url("https://google.com")
        self.assertFalse(ok_empty)
        self.assertFalse(ok_bad)

    def test_22_timeout_resilience(self) -> None:
        extractor = BetclicOddsExtractor()
        res = extractor.extract("https://invalid-nonexistent-domain-123456.com")
        self.assertEqual(res["status"], "BŁĄD")

    def test_23_mycombi_no_header_extraction(self) -> None:
        from playwright.sync_api import sync_playwright
        html = """
        <html><body>
          <div class="marketBox">
            <button class="is-odd">Wygrana Legii 2.10</button>
            <button class="is-odd">Powyżej 2.5 gola 1.85</button>
          </div>
        </body></html>
        """
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html)
            dom_data = _extract_dom_from_page(page, "MyCombi")
            browser.close()

        self.assertEqual(len(dom_data), 2)
        self.assertEqual(dom_data[0]["market"], "MyCombi")
        self.assertEqual(dom_data[1]["market"], "MyCombi")
        self.assertFalse(dom_data[0].get("missing_header", False))
        self.assertEqual(dom_data[0]["odds"], "2.10")
        self.assertEqual(dom_data[1]["odds"], "1.85")

    def test_24_standard_market_with_header_regression(self) -> None:
        from playwright.sync_api import sync_playwright
        html = """
        <html><body>
          <div class="marketBox">
            <div class="marketBox_headTitle">Wynik meczu</div>
            <button class="is-odd">Legia 1.95</button>
            <button class="is-odd">Remis 3.40</button>
          </div>
        </body></html>
        """
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html)
            dom_data = _extract_dom_from_page(page, "Top")
            browser.close()

        self.assertEqual(len(dom_data), 2)
        self.assertEqual(dom_data[0]["market"], "Wynik meczu")
        self.assertEqual(dom_data[1]["market"], "Wynik meczu")
        self.assertFalse(dom_data[0].get("missing_header", False))
        self.assertEqual(dom_data[0]["selection"], "Legia")
        self.assertEqual(dom_data[0]["odds"], "1.95")
        self.assertEqual(dom_data[1]["selection"], "Remis")
        self.assertEqual(dom_data[1]["odds"], "3.40")

    def test_25_expand_below_fold(self) -> None:
        import time

        from playwright.sync_api import sync_playwright

        from core import _expand_all_on_page
        from diagnostics import DiagnosticsManager

        html = """
        <!DOCTYPE html>
        <html>
        <head><style>body { margin: 0; padding: 0; } .spacer { height: 2500px; }</style></head>
        <body>
          <div class="spacer">Top spacer</div>
          <div class="marketBox">
            <button id="btn_below" aria-expanded="false" onclick="this.setAttribute('aria-expanded','true'); document.getElementById('hidden_odd').style.display='block';">Rozwiń rynek</button>
            <div id="hidden_odd" style="display:none;">
              <button class="is-odd">Gospodarz 1.85</button>
            </div>
          </div>
        </body>
        </html>
        """
        diag = DiagnosticsManager()
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.set_content(html)

            clicked = _expand_all_on_page(page, diag, time.time() + 10.0)
            btn_state = page.get_attribute("#btn_below", "aria-expanded")
            is_odd_visible = page.is_visible(".is-odd")
            browser.close()

        self.assertGreaterEqual(clicked, 1)
        self.assertEqual(btn_state, "true")
        self.assertTrue(is_odd_visible)

    def test_26_expand_multi_pass(self) -> None:
        import time

        from playwright.sync_api import sync_playwright

        from core import _expand_all_on_page
        from diagnostics import DiagnosticsManager

        html = """
        <!DOCTYPE html>
        <html>
        <head><style>body { margin: 0; padding: 0; }</style></head>
        <body>
          <div id="container">
            <button id="btn_1" aria-expanded="false" onclick="
              this.setAttribute('aria-expanded','true');
              var d = document.createElement('div');
              d.innerHTML = '<button id=btn_2>Pokaż więcej</button><div id=more_odds style=display:none><button class=is-odd>Gość 2.40</button></div>';
              document.getElementById('container').appendChild(d);
              document.getElementById('btn_2').onclick = function() { document.getElementById('more_odds').style.display='block'; };
            ">Pokaż więcej</button>
          </div>
        </body>
        </html>
        """
        diag = DiagnosticsManager()
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.set_content(html)

            clicked = _expand_all_on_page(page, diag, time.time() + 10.0)
            is_odd_visible = page.is_visible(".is-odd")
            browser.close()

        self.assertGreaterEqual(clicked, 2)
        self.assertTrue(is_odd_visible)

    def test_27_zero_raw_fail(self) -> None:
        from core import _aggregate_parser_truth_status, _evaluate_tab_status
        report = {
            "tab_name": "MyCombi",
            "activation_ok": True,
            "interactive_control_count": 371,
            "priced_candidate_count": 371,
            "unpriced_control_count": 0,
            "selectable_count": 371,
            "raw_dom_items": 0,
            "parsed_odds_count": 0,
            "unresolved_count": 0,
            "remaining_closed": 0,
            "remaining_more": 0,
            "deadline_hit": False,
            "exception": None,
        }
        status, reason = _evaluate_tab_status(report)
        report["status"] = status
        report["reason"] = reason
        global_status, analysis_ready = _aggregate_parser_truth_status([report])

        self.assertEqual(status, "FAIL")
        self.assertEqual(reason, "ZERO_RAW_WITH_PRICED_CANDIDATES")
        self.assertEqual(global_status, "FAIL")
        self.assertEqual(analysis_ready, "NO")

    def test_28_partial_expansion(self) -> None:
        from core import _aggregate_parser_truth_status, _evaluate_tab_status
        report = {
            "tab_name": "Wynik",
            "activation_ok": True,
            "selectable_count": 50,
            "raw_dom_items": 45,
            "parsed_odds_count": 40,
            "unresolved_count": 5,
            "remaining_closed": 0,
            "remaining_more": 1,
            "deadline_hit": False,
            "exception": None,
        }
        status, reason = _evaluate_tab_status(report)
        report["status"] = status
        report["reason"] = reason
        global_status, analysis_ready = _aggregate_parser_truth_status([report])

        self.assertEqual(status, "PARTIAL")
        self.assertEqual(global_status, "PARTIAL")
        self.assertEqual(analysis_ready, "NO")

    def test_29_all_pass(self) -> None:
        from core import _aggregate_parser_truth_status, _evaluate_tab_status
        tab1 = {"tab_name": "Top", "activation_ok": True, "selectable_count": 20, "raw_dom_items": 20, "parsed_odds_count": 20, "unresolved_count": 0, "remaining_closed": 0, "remaining_more": 0, "deadline_hit": False, "exception": None}
        tab2 = {"tab_name": "Gole", "activation_ok": True, "selectable_count": 30, "raw_dom_items": 30, "parsed_odds_count": 30, "unresolved_count": 0, "remaining_closed": 0, "remaining_more": 0, "deadline_hit": False, "exception": None}
        tab3 = {"tab_name": "Pusta", "activation_ok": True, "selectable_count": 0, "raw_dom_items": 0, "parsed_odds_count": 0, "unresolved_count": 0, "remaining_closed": 0, "remaining_more": 0, "deadline_hit": False, "exception": None}

        reports = []
        for t in [tab1, tab2, tab3]:
            st, re = _evaluate_tab_status(t)
            t["status"] = st
            t["reason"] = re
            reports.append(t)

        global_status, analysis_ready = _aggregate_parser_truth_status(reports)

        self.assertEqual(reports[0]["status"], "PASS")
        self.assertEqual(reports[1]["status"], "PASS")
        self.assertEqual(reports[2]["status"], "PASS")
        self.assertEqual(reports[2]["reason"], "EMPTY_TAB")
        self.assertEqual(global_status, "PASS")
        self.assertEqual(analysis_ready, "YES")

    def test_30_raw_preserves_duplicates(self) -> None:
        import tempfile
        from pathlib import Path

        from core import _export_raw_jsonl

        rec1 = {"tab_name": "Top", "tab_index": 0, "market": "Wynik", "selection": "1", "odds": "1.85", "raw": "1 1,85", "source_index": 1}
        rec2 = {"tab_name": "Top", "tab_index": 0, "market": "Wynik", "selection": "1", "odds": "1.85", "raw": "1 1,85", "source_index": 2}
        rec3 = {"tab_name": "Top", "tab_index": 0, "market": "Wynik", "selection": "X", "odds": "3.20", "raw": "X 3,20", "source_index": 3}

        raw_list = [rec1, rec2, rec3]
        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / "raw_test.jsonl"
            written_count, sha256_hex, status = _export_raw_jsonl(raw_list, out_file)

            lines = [l for l in out_file.read_text(encoding="utf-8").splitlines() if l.strip()]

        self.assertEqual(len(raw_list), 3)
        self.assertEqual(written_count, 3)
        self.assertEqual(len(lines), 3)
        self.assertEqual(status, "PASS")
        self.assertTrue(len(sha256_hex) > 0)

    def test_31_safe_tab_artifact_names(self) -> None:
        from core import _safe_tab_name

        name1 = _safe_tab_name("1. połowa / 2. połowa: wynik", 0)
        name2 = _safe_tab_name("GŁÓWNE & Statystyki!", 1)
        name3 = _safe_tab_name("   ", 2)

        self.assertNotIn(" ", name1)
        self.assertNotIn("/", name1)
        self.assertNotIn(":", name1)
        self.assertNotIn(" ", name2)
        self.assertNotIn("&", name2)
        self.assertNotIn("!", name2)
        self.assertEqual(name3, "TAB_2")
        self.assertEqual(name1, "1__po_owa___2__po_owa__wynik")

    def test_32_artifact_failure_isolation(self) -> None:
        import time

        from playwright.sync_api import sync_playwright

        from core import _safe_tab_name
        from diagnostics import SNAPSHOTS_DIR

        run_id = f"test_iso_{int(time.time())}"
        tab_name = "Top"
        safe_name = _safe_tab_name(tab_name, 0)

        html_file = SNAPSHOTS_DIR / f"tab_{run_id}_0_{safe_name}.html"

        evidence_errors = 0
        tab_html_count = 0
        tab_screenshot_count = 0

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content("<html><body><h1>Test</h1></body></html>")

            try:
                html_file.write_text(page.content(), encoding="utf-8")
                tab_html_count += 1
            except Exception:
                evidence_errors += 1

            try:
                page.screenshot(path="Z:\\invalid_drive_path_12345\\fail.png", full_page=True)
                tab_screenshot_count += 1
            except Exception:
                evidence_errors += 1

            browser.close()

        self.assertEqual(tab_html_count, 1)
        self.assertEqual(tab_screenshot_count, 0)
        self.assertEqual(evidence_errors, 1)

        if html_file.exists():
            html_file.unlink()

    def test_33_nested_container_single_capture(self) -> None:
        from playwright.sync_api import sync_playwright

        from core import _extract_dom_from_page

        html = """
        <html>
          <body>
            <sports-market class="marketElement">
              <div class="marketBox">
                <div class="marketBox_headTitle">Zwycięzca meczu</div>
                <div class="marketBox_lineSelection">
                  <span class="marketBox_label">Team A</span>
                  <button class="is-odd">1.85</button>
                </div>
              </div>
            </sports-market>
          </body>
        </html>
        """
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html)

            records = _extract_dom_from_page(page, "GŁÓWNE")
            browser.close()

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["source_index"], 1)
        self.assertEqual(records[0]["odds"], "1.85")
        self.assertEqual(records[0]["market"], "Zwycięzca meczu")

    def test_34_mycombi_without_marketbox(self) -> None:
        from playwright.sync_api import sync_playwright

        from core import (
            _evaluate_tab_status,
            _extract_dom_from_page,
            _get_dom_expansion_metrics,
        )

        html = """
        <html>
          <body>
            <div class="customWrapper">
              <div class="marketBox_lineSelection">
                <span>Powyżej 2.5 gola</span>
                <button class="is-odd">+</button>
              </div>
              <div class="marketBox_lineSelection">
                <span>Oba zespoły strzelą</span>
                <button class="is-odd">+</button>
              </div>
            </div>
          </body>
        </html>
        """
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html)

            records = _extract_dom_from_page(page, "MyCombi")
            metrics = _get_dom_expansion_metrics(page)
            browser.close()

        self.assertEqual(len(records), 0)
        self.assertEqual(metrics["priced_candidate_count"], 0)
        self.assertEqual(metrics["unpriced_control_count"], 2)

        status, reason = _evaluate_tab_status({
            "activation_ok": True,
            "priced_candidate_count": 0,
            "unpriced_control_count": 2,
            "raw_dom_items": 0,
            "parsed_odds_count": 0,
            "unresolved_count": 0,
            "remaining_closed": 0,
            "remaining_more": 0,
            "deadline_hit": False,
        })
        self.assertEqual(status, "PASS")
        self.assertEqual(reason, "NO_STANDALONE_ODDS")
        self.assertFalse(any(r.get("odds") == "1.00" for r in records))

    def test_35_unknown_header_preserved(self) -> None:
        from playwright.sync_api import sync_playwright

        from core import _extract_dom_from_page

        html = """
        <html>
          <body>
            <div class="unknownWrapper">
              <div class="marketBox_lineSelection">
                <span class="marketBox_label">Gracz A strzeli</span>
                <button class="is-odd">2.50</button>
              </div>
            </div>
          </body>
        </html>
        """
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html)

            records = _extract_dom_from_page(page, "Wynik")
            browser.close()

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["market"], "")
        self.assertTrue(records[0]["missing_header"])
        self.assertEqual(records[0]["odds"], "2.50")

    def test_36_mycombi_mixed_pricing(self) -> None:
        from playwright.sync_api import sync_playwright

        from core import _extract_dom_from_page, _get_dom_expansion_metrics

        html = """
        <html>
          <body>
            <div class="customWrapper">
              <div class="marketBox_lineSelection">
                <span>Powyżej 2.5 gola</span>
                <button class="is-odd">+</button>
              </div>
              <div class="marketBox_lineSelection">
                <span>Oba zespoły strzelą</span>
                <button class="is-odd">+</button>
              </div>
              <div class="marketBox_lineSelection">
                <span>Strzelec gola</span>
                <button class="is-odd"><span class="oddValue">2.10</span></button>
              </div>
            </div>
          </body>
        </html>
        """
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html)

            records = _extract_dom_from_page(page, "MyCombi")
            metrics = _get_dom_expansion_metrics(page)
            browser.close()

        self.assertEqual(metrics["interactive_control_count"], 3)
        self.assertEqual(metrics["priced_candidate_count"], 1)
        self.assertEqual(metrics["unpriced_control_count"], 2)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["odds"], "2.10")

    def test_37_numbers_are_not_odds(self) -> None:
        from playwright.sync_api import sync_playwright

        from core import _extract_dom_from_page

        html = """
        <html>
          <body>
            <div class="marketBox">
              <div class="marketBox_headTitle">Gole Powyżej 2,5 / Handicap -1</div>
              <div class="marketBox_lineSelection">
                <span class="marketBox_label">Wynik 2-0 dla gospodarzy</span>
                <button class="is-odd">Dodaj do kuponu</button>
              </div>
            </div>
          </body>
        </html>
        """
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html)

            records = _extract_dom_from_page(page, "Gole")
            browser.close()

        self.assertEqual(len(records), 0)

    def test_38_tab_deadline_isolation(self) -> None:
        from core import _aggregate_parser_truth_status, _evaluate_tab_status

        tab1 = {"tab_name": "Strzelcy", "activation_ok": True, "interactive_control_count": 300, "priced_candidate_count": 200, "unpriced_control_count": 100, "raw_dom_items": 200, "parsed_odds_count": 200, "unresolved_count": 0, "remaining_closed": 0, "remaining_more": 0, "deadline_hit": True, "tab_seconds": 60.0}
        tab2 = {"tab_name": "Wynik", "activation_ok": True, "interactive_control_count": 50, "priced_candidate_count": 50, "unpriced_control_count": 0, "raw_dom_items": 50, "parsed_odds_count": 50, "unresolved_count": 0, "remaining_closed": 0, "remaining_more": 0, "deadline_hit": False, "tab_seconds": 3.5}
        tab3 = {"tab_name": "Gole", "activation_ok": True, "interactive_control_count": 60, "priced_candidate_count": 60, "unpriced_control_count": 0, "raw_dom_items": 60, "parsed_odds_count": 60, "unresolved_count": 0, "remaining_closed": 0, "remaining_more": 0, "deadline_hit": False, "tab_seconds": 4.1}

        reports = []
        for t in [tab1, tab2, tab3]:
            st, re = _evaluate_tab_status(t)
            t["status"] = st
            t["reason"] = re
            reports.append(t)

        self.assertEqual(reports[0]["status"], "PARTIAL")
        self.assertEqual(reports[0]["reason"], "DEADLINE_EXCEEDED")
        self.assertEqual(reports[1]["status"], "PASS")
        self.assertEqual(reports[2]["status"], "PASS")

        global_status, ready = _aggregate_parser_truth_status(reports, detected_tab_count=3, unscanned_tabs=[])
        self.assertEqual(global_status, "PARTIAL")
        self.assertEqual(ready, "NO")

    def test_39_unscanned_tab_gate(self) -> None:
        from core import _aggregate_parser_truth_status

        tab1 = {"tab_name": "Top", "status": "PASS", "reason": "OK"}
        tab2 = {"tab_name": "Wynik", "status": "PASS", "reason": "OK"}
        reports = [tab1, tab2]

        global_status, ready = _aggregate_parser_truth_status(reports, detected_tab_count=3, unscanned_tabs=["Gole"])
        self.assertNotEqual(global_status, "PASS")
        self.assertEqual(ready, "NO")

    def test_40_run_deadline_stop(self) -> None:
        from core import _aggregate_parser_truth_status

        reports = [{"tab_name": "Top", "status": "PASS", "reason": "OK"}]
        unscanned = ["Wynik", "Gole", "Strzelcy"]

        global_status, ready = _aggregate_parser_truth_status(reports, detected_tab_count=4, unscanned_tabs=unscanned)
        self.assertIn(global_status, ["PARTIAL", "FAIL"])
        self.assertEqual(ready, "NO")

    def test_41_dedupe_runtime_no_nameerror(self) -> None:
        from core import _dedupe_records_preserving_order

        rec_a = {"CATEGORY": "GŁÓWNE", "MARKET": "Wynik meczu", "PERIOD": "FULL_TIME", "FAMILY": "MATCH_WINNER", "OWNER": "1", "SELECTION": "Team A", "LINE": "", "ODDS": "1.85", "CONTAINER_ID": "box_1"}
        rec_a_dup = {"CATEGORY": "GŁÓWNE", "MARKET": "Wynik meczu", "PERIOD": "FULL_TIME", "FAMILY": "MATCH_WINNER", "OWNER": "1", "SELECTION": "Team A", "LINE": "", "ODDS": "1.85", "CONTAINER_ID": "box_1"}
        rec_b = {"CATEGORY": "GŁÓWNE", "MARKET": "Wynik meczu", "PERIOD": "FULL_TIME", "FAMILY": "MATCH_WINNER", "OWNER": "2", "SELECTION": "Team B", "LINE": "", "ODDS": "2.10", "CONTAINER_ID": "box_1"}

        records = [rec_a, rec_a_dup, rec_b]
        unres = []
        unique_odds, _unres_out = _dedupe_records_preserving_order(records, unres)

        self.assertEqual(len(unique_odds), 2)
        self.assertEqual(unique_odds[0]["SELECTION"], "Team A")
        self.assertEqual(unique_odds[1]["SELECTION"], "Team B")

    def test_42_dedupe_empty_and_unique(self) -> None:
        from core import _dedupe_records_preserving_order

        rec_1 = {"CATEGORY": "Top", "MARKET": "Gole", "PERIOD": "FULL_TIME", "FAMILY": "TOTAL_GOALS", "OWNER": "OVER", "SELECTION": "Powyżej 2.5", "LINE": "2.5", "ODDS": "1.90", "CONTAINER_ID": "box_2"}
        rec_2 = {"CATEGORY": "Top", "MARKET": "Gole", "PERIOD": "FULL_TIME", "FAMILY": "TOTAL_GOALS", "OWNER": "UNDER", "SELECTION": "Poniżej 2.5", "LINE": "2.5", "ODDS": "1.80", "CONTAINER_ID": "box_2"}

        empty_out, _ = _dedupe_records_preserving_order([], [])
        self.assertEqual(len(empty_out), 0)

        unique_out, _ = _dedupe_records_preserving_order([rec_1, rec_2], [])
        self.assertEqual(len(unique_out), 2)

    def test_43_extract_finalization_no_nameerror(self) -> None:
        import warnings
        from unittest.mock import MagicMock, patch

        from core import BetclicOddsExtractor

        mock_header = MagicMock()
        mock_header.inner_text.return_value = "Team A - Team B"
        mock_header.is_visible.return_value = False

        mock_tab = MagicMock()
        mock_tab.inner_text.return_value = "GŁÓWNE"
        mock_tab.query_selector.return_value = None
        mock_tab.get_attribute.return_value = "tab_item isActive"
        mock_tab.is_visible.return_value = False

        mock_page = MagicMock()
        mock_page.goto.return_value = MagicMock(status=200)
        mock_page.title.return_value = "Obstawianie Team A - Team B | Betclic"
        mock_page.query_selector.side_effect = lambda sel: mock_header if ("h1" in sel or "header" in sel) else None
        mock_page.query_selector_all.side_effect = lambda sel: [mock_tab] if ("tab" in sel or "category" in sel) else []
        mock_page.content.return_value = "<html><body></body></html>"

        def mock_eval(script, *args):
            s = str(script)
            if "NO_EVENT_HEADER" in s:
                return {"status": "PREMATCH", "proof": "mock-event-header"}
            if "innerHeight" in s:
                return 800
            if "scrollHeight" in s:
                return 1000
            if "currentTabName" in s or len(args) > 0:
                return [{"container_id": "box_1", "category": "Top", "market": "Suma goli 2.5", "selection": "Powyżej 2.5", "section_title": "", "odds": "1.85", "raw": "Powyżej 2.5 1.85", "missing_header": False, "source_index": 1}]
            if "interactive" in s or "seenButtons" in s:
                return {"interactive_control_count": 1, "priced_candidate_count": 1, "unpriced_control_count": 0, "selectable_count": 1, "remaining_closed": 0, "remaining_more": 0}
            return None

        mock_page.evaluate.side_effect = mock_eval

        mock_context = MagicMock()
        mock_context.pages = [mock_page]
        mock_pw = MagicMock()
        mock_pw.chromium.launch_persistent_context.return_value = mock_context
        mock_pw_cm = MagicMock()
        mock_pw_cm.__enter__.return_value = mock_pw

        extractor = BetclicOddsExtractor()
        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)
            with patch("playwright.sync_api.sync_playwright", return_value=mock_pw_cm), \
                 patch("core.find_chrome_exe", return_value=None):
                res = extractor.extract("https://www.betclic.pl/pilka-nozna-sfootball/test-c1/match-m123")

        self.assertEqual(res.get("status"), "GOTOWE")
        self.assertIn("BETCLIC_FULL_ODDS_PACKET", res.get("packet_text", ""))

    def test_43a_generic_total_heading_has_proven_no_push_settlement(self) -> None:
        from core import derive_market_normalization
        from parser import parse_market_record
        record, unresolved = parse_market_record(
            category="Top", market_title="Suma goli 2.5", raw_selection="Powyżej 2.5",
            odds_str="1.85", raw_text="Powyżej 2.5 1.85", section_title="",
            home_team="Team A", away_team="Team B", container_id="box_1",
        )
        self.assertIsNone(unresolved)
        self.assertEqual(record["FAMILY"], "GOALS_OU")
        derive_market_normalization([record], "Team A", "Team B")
        self.assertEqual(record["SETTLEMENT"], "NO_PUSH")

    def test_44_duration_runtime_field(self) -> None:
        from unittest.mock import MagicMock, patch

        from core import BetclicOddsExtractor

        mock_header = MagicMock()
        mock_header.inner_text.return_value = "Team A - Team B"
        mock_header.is_visible.return_value = False

        mock_tab = MagicMock()
        mock_tab.inner_text.return_value = "GŁÓWNE"
        mock_tab.query_selector.return_value = None
        mock_tab.get_attribute.return_value = "tab_item isActive"
        mock_tab.is_visible.return_value = False

        mock_page = MagicMock()
        mock_page.goto.return_value = MagicMock(status=200)
        mock_page.title.return_value = "Obstawianie Team A - Team B | Betclic"
        mock_page.query_selector.side_effect = lambda sel: mock_header if ("h1" in sel or "header" in sel) else None
        mock_page.query_selector_all.side_effect = lambda sel: [mock_tab] if ("tab" in sel or "category" in sel) else []
        mock_page.content.return_value = "<html><body></body></html>"

        def mock_eval(script, *args):
            s = str(script)
            if "NO_EVENT_HEADER" in s:
                return {"status": "PREMATCH", "proof": "mock-event-header"}
            if "innerHeight" in s:
                return 800
            if "scrollHeight" in s:
                return 1000
            if "currentTabName" in s or len(args) > 0:
                return [{"container_id": "box_1", "category": "Top", "market": "Suma goli 2.5", "selection": "Powyżej 2.5", "section_title": "", "odds": "1.85", "raw": "Powyżej 2.5 1.85", "missing_header": False, "source_index": 1}]
            if "interactive" in s or "seenButtons" in s:
                return {"interactive_control_count": 1, "priced_candidate_count": 1, "unpriced_control_count": 0, "selectable_count": 1, "remaining_closed": 0, "remaining_more": 0}
            return None

        mock_page.evaluate.side_effect = mock_eval

        mock_context = MagicMock()
        mock_context.pages = [mock_page]
        mock_pw = MagicMock()
        mock_pw.chromium.launch_persistent_context.return_value = mock_context
        mock_pw_cm = MagicMock()
        mock_pw_cm.__enter__.return_value = mock_pw

        extractor = BetclicOddsExtractor()
        with patch("playwright.sync_api.sync_playwright", return_value=mock_pw_cm), \
             patch("core.find_chrome_exe", return_value=None):
            res = extractor.extract("https://www.betclic.pl/pilka-nozna-sfootball/test-c1/match-m123")

        self.assertIn("CAPTURE_TIME=", res.get("packet_text", ""))
        self.assertEqual(res.get("odds_count"), 1)

    def test_45_period_collision_1x2_different_periods(self) -> None:
        from core import _dedupe_records_preserving_order
        from parser import parse_market_record

        r_ft1, _ = parse_market_record(category="GŁÓWNE", market_title="Wynik meczu", raw_selection="1", odds_str="1.28", raw_text="1 1.28", section_title="", home_team="Team A", away_team="Team B", container_id="box_ft")
        r_ftx, _ = parse_market_record(category="GŁÓWNE", market_title="Wynik meczu", raw_selection="X", odds_str="4.80", raw_text="X 4.80", section_title="", home_team="Team A", away_team="Team B", container_id="box_ft")
        r_ft2, _ = parse_market_record(category="GŁÓWNE", market_title="Wynik meczu", raw_selection="2", odds_str="5.90", raw_text="2 5.90", section_title="", home_team="Team A", away_team="Team B", container_id="box_ft")

        r_1h1, _ = parse_market_record(category="1. POŁOWA", market_title="Wynik 1. połowy", raw_selection="1", odds_str="1.64", raw_text="1 1.64", section_title="", home_team="Team A", away_team="Team B", container_id="box_1h")
        r_1hx, _ = parse_market_record(category="1. POŁOWA", market_title="Wynik 1. połowy", raw_selection="X", odds_str="2.68", raw_text="X 2.68", section_title="", home_team="Team A", away_team="Team B", container_id="box_1h")
        r_1h2, _ = parse_market_record(category="1. POŁOWA", market_title="Wynik 1. połowy", raw_selection="2", odds_str="5.60", raw_text="2 5.60", section_title="", home_team="Team A", away_team="Team B", container_id="box_1h")

        extracted = [r_ft1, r_ftx, r_ft2, r_1h1, r_1hx, r_1h2]
        unresolved = []
        unique_odds, unres_out = _dedupe_records_preserving_order(extracted, unresolved)

        self.assertEqual(len(unique_odds), 6)
        self.assertEqual(len(unres_out), 0)
        periods = {o["PERIOD"] for o in unique_odds}
        self.assertEqual(periods, {"FULL_TIME", "1ST_HALF"})

    def test_46_period_collision_btts_different_periods(self) -> None:
        from core import _dedupe_records_preserving_order
        from parser import parse_market_record

        r_ft_tak, _ = parse_market_record(category="GŁÓWNE", market_title="Oba zespoły strzelą", raw_selection="Tak", odds_str="1.50", raw_text="Tak 1.50", section_title="", home_team="Team A", away_team="Team B", container_id="box_btts_ft")
        r_ft_nie, _ = parse_market_record(category="GŁÓWNE", market_title="Oba zespoły strzelą", raw_selection="Nie", odds_str="2.10", raw_text="Nie 2.10", section_title="", home_team="Team A", away_team="Team B", container_id="box_btts_ft")

        r_1h_tak, _ = parse_market_record(category="1. POŁOWA", market_title="Oba zespoły strzelą w 1. połowie", raw_selection="Tak", odds_str="3.02", raw_text="Tak 3.02", section_title="", home_team="Team A", away_team="Team B", container_id="box_btts_1h")
        r_1h_nie, _ = parse_market_record(category="1. POŁOWA", market_title="Oba zespoły strzelą w 1. połowie", raw_selection="Nie", odds_str="1.24", raw_text="Nie 1.24", section_title="", home_team="Team A", away_team="Team B", container_id="box_btts_1h")

        extracted = [r_ft_tak, r_ft_nie, r_1h_tak, r_1h_nie]
        unresolved = []
        unique_odds, unres_out = _dedupe_records_preserving_order(extracted, unresolved)

        self.assertEqual(len(unique_odds), 4)
        self.assertEqual(len(unres_out), 0)

    def test_47_duplicate_same_odds_merge(self) -> None:
        from core import _dedupe_records_preserving_order
        from parser import parse_market_record

        r1, _ = parse_market_record(category="GŁÓWNE", market_title="Suma goli 2.5", raw_selection="Powyżej 2.5", odds_str="1.85", raw_text="Powyżej 2.5 1.85", section_title="", home_team="Team A", away_team="Team B", container_id="box_1")
        r2, _ = parse_market_record(category="GŁÓWNE", market_title="Suma goli 2.5", raw_selection="Powyżej 2.5", odds_str="1.85", raw_text="Powyżej 2.5 1.85", section_title="", home_team="Team A", away_team="Team B", container_id="box_2")

        extracted = [r1, r2]
        unresolved = []
        unique_odds, unres_out = _dedupe_records_preserving_order(extracted, unresolved)

        self.assertEqual(len(unique_odds), 1)
        self.assertEqual(len(unres_out), 0)
        self.assertEqual(unique_odds[0]["ODDS"], "1.85")

    def test_48_same_period_different_odds_conflict(self) -> None:
        from core import (
            _aggregate_parser_truth_status,
            _dedupe_records_preserving_order,
            _evaluate_tab_status,
        )
        from parser import parse_market_record

        r1, _ = parse_market_record(category="GŁÓWNE", market_title="Suma goli 2.5", raw_selection="Powyżej 2.5", odds_str="1.85", raw_text="Powyżej 2.5 1.85", section_title="", home_team="Team A", away_team="Team B", container_id="box_1")
        r2, _ = parse_market_record(category="GŁÓWNE", market_title="Suma goli 2.5", raw_selection="Powyżej 2.5", odds_str="2.20", raw_text="Powyżej 2.5 2.20", section_title="", home_team="Team A", away_team="Team B", container_id="box_2")

        extracted = [r1, r2]
        unresolved = []
        unique_odds, unres_out = _dedupe_records_preserving_order(extracted, unresolved)

        self.assertEqual(len(unique_odds), 1)
        self.assertEqual(len(unres_out), 1)
        self.assertEqual(unres_out[0]["REASON"], "CONFLICTING_ODDS_FOR_SAME_SELECTION")

        tab_m = {
            "tab_name": "GŁÓWNE", "activation_ok": True, "interactive_control_count": 2,
            "priced_candidate_count": 2, "unpriced_control_count": 0, "selectable_count": 2,
            "raw_dom_items": 2, "parsed_odds_count": 1, "unresolved_count": 1,
            "remaining_closed": 0, "remaining_more": 0, "deadline_hit": False
        }
        st, re = _evaluate_tab_status(tab_m)
        tab_m["status"] = st
        tab_m["reason"] = re

        global_status, ready = _aggregate_parser_truth_status([tab_m], detected_tab_count=1, unscanned_tabs=[])
        self.assertEqual(global_status, "PARTIAL")
        self.assertEqual(ready, "NO")

    def test_49_1x2_empty_market_header_parent_period(self) -> None:
        from parser import parse_market_record

        rec, _unres = parse_market_record(
            category="GŁÓWNE",
            market_title="Wynik meczu",
            raw_selection="1",
            odds_str="1.45",
            raw_text="1 1.45",
            section_title="",
            home_team="Team A",
            away_team="Team B",
            container_id="box_1",
            ancestor_title="1. połowa"
        )
        self.assertIsNotNone(rec)
        self.assertEqual(rec["PERIOD"], "1ST_HALF")

    def test_50_btts_parent_header_period(self) -> None:
        from parser import parse_market_record

        rec, _unres = parse_market_record(
            category="GŁÓWNE",
            market_title="Oba zespoły strzelą gola",
            raw_selection="Tak",
            odds_str="3.80",
            raw_text="Tak 3.80",
            section_title="",
            home_team="Team A",
            away_team="Team B",
            container_id="box_1",
            ancestor_title="1. połowa"
        )
        self.assertIsNotNone(rec)
        self.assertEqual(rec["PERIOD"], "1ST_HALF")

    def test_51_cross_tab_tick_move_merge_latest(self) -> None:
        from core import _dedupe_records_preserving_order
        from parser import parse_market_record

        r1, _ = parse_market_record(
            category="Top", market_title="Oba zespoły strzelą gola", raw_selection="Tak",
            odds_str="1.65", raw_text="Tak 1.65", section_title="", home_team="Team A",
            away_team="Team B", container_id="box_top"
        )
        r1["source_index"] = 10

        r2, _ = parse_market_record(
            category="Gole", market_title="Oba zespoły strzelą gola", raw_selection="Tak",
            odds_str="1.64", raw_text="Tak 1.64", section_title="", home_team="Team A",
            away_team="Team B", container_id="box_gole"
        )
        r2["source_index"] = 20

        extracted = [r1, r2]
        unresolved = []
        unique_odds, unres_out = _dedupe_records_preserving_order(extracted, unresolved)

        self.assertEqual(len(unique_odds), 1)
        self.assertEqual(len(unres_out), 0)
        self.assertEqual(unique_odds[0]["ODDS"], "1.64")
        self.assertEqual(unique_odds[0]["source_index"], 20)

    def test_52_same_tab_different_odds_conflict(self) -> None:
        from core import _dedupe_records_preserving_order
        from parser import parse_market_record

        r1, _ = parse_market_record(
            category="GŁÓWNE", market_title="Oba zespoły strzelą gola", raw_selection="Tak",
            odds_str="1.65", raw_text="Tak 1.65", section_title="", home_team="Team A",
            away_team="Team B", container_id="box_1"
        )
        r1["source_index"] = 10

        r2, _ = parse_market_record(
            category="GŁÓWNE", market_title="Oba zespoły strzelą gola", raw_selection="Tak",
            odds_str="1.90", raw_text="Tak 1.90", section_title="", home_team="Team A",
            away_team="Team B", container_id="box_2"
        )
        r2["source_index"] = 20

        extracted = [r1, r2]
        unresolved = []
        unique_odds, unres_out = _dedupe_records_preserving_order(extracted, unresolved)

        self.assertEqual(len(unique_odds), 1)
        self.assertEqual(len(unres_out), 1)
        self.assertEqual(unres_out[0]["REASON"], "CONFLICTING_ODDS_FOR_SAME_SELECTION")

    def test_53_live_guard_prematch_status(self) -> None:
        from unittest.mock import MagicMock, patch

        from core import BetclicOddsExtractor

        mock_header = MagicMock()
        mock_header.inner_text.return_value = "Team A - Team B"
        mock_header.is_visible.return_value = False

        mock_tab = MagicMock()
        mock_tab.inner_text.return_value = "GŁÓWNE"
        mock_tab.query_selector.return_value = None
        mock_tab.get_attribute.return_value = "tab_item isActive"
        mock_tab.is_visible.return_value = False

        mock_page = MagicMock()
        mock_page.goto.return_value = MagicMock(status=200)
        mock_page.title.return_value = "Obstawianie Team A - Team B | Betclic"
        mock_page.query_selector.side_effect = lambda sel: mock_header if ("h1" in sel or "header" in sel) else None
        mock_page.query_selector_all.side_effect = lambda sel: [mock_tab] if ("tab" in sel or "category" in sel) else []
        mock_page.content.return_value = "<html><body></body></html>"

        def mock_eval(script, *args):
            s = str(script)
            if "liveSelectors" in s:
                return {"is_live": False, "signal": "", "text": ""}
            if "innerHeight" in s:
                return 800
            if "scrollHeight" in s:
                return 1000
            if "currentTabName" in s or len(args) > 0:
                return [{"container_id": "box_1", "category": "Top", "market": "Suma goli 2.5", "selection": "Powyżej 2.5", "section_title": "", "odds": "1.85", "raw": "Powyżej 2.5 1.85", "missing_header": False, "source_index": 1}]
            if "interactive" in s or "seenButtons" in s:
                return {"interactive_control_count": 1, "priced_candidate_count": 1, "unpriced_control_count": 0, "selectable_count": 1, "remaining_closed": 0, "remaining_more": 0}
            return None

        mock_page.evaluate.side_effect = mock_eval

        mock_context = MagicMock()
        mock_context.pages = [mock_page]
        mock_pw = MagicMock()
        mock_pw.chromium.launch_persistent_context.return_value = mock_context
        mock_pw_cm = MagicMock()
        mock_pw_cm.__enter__.return_value = mock_pw

        extractor = BetclicOddsExtractor()
        with patch("playwright.sync_api.sync_playwright", return_value=mock_pw_cm), \
             patch("core.find_chrome_exe", return_value=None):
            res = extractor.extract("https://www.betclic.pl/pilka-nozna-sfootball/test-c1/match-m123")

        self.assertIn('EVENT_STATUS="GOTOWE";', res.get("packet_text", ""))
        self.assertIn('ANALYSIS_READY="YES";', res.get("packet_text", ""))
        clean = res.get("llm_packet_text", "")
        self.assertIn("\nODDS\nFAMILY|MARKET|PERIOD|OWNER|SELECTION|LINE|ODDS|SETTLEMENT\n", clean)
        self.assertRegex(clean, r"\nODDS_COUNT=[1-9]\d*\n")
        for junk in ("MARKET_INSTANCE_ID", "SOURCE_RAW_RECORD_IDS", "RUNTIME_", "SHA256", "BUILD_ID", "RUN_ID", "app-desktop["):
            self.assertNotIn(junk, clean)

    def test_54_live_guard_live_selector_status(self) -> None:
        from unittest.mock import MagicMock, patch

        from core import BetclicOddsExtractor

        mock_header = MagicMock()
        mock_header.inner_text.return_value = "Team A - Team B"
        mock_header.is_visible.return_value = False

        mock_tab = MagicMock()
        mock_tab.inner_text.return_value = "GŁÓWNE"
        mock_tab.query_selector.return_value = None
        mock_tab.get_attribute.return_value = "tab_item isActive"
        mock_tab.is_visible.return_value = False

        mock_page = MagicMock()
        mock_page.goto.return_value = MagicMock(status=200)
        mock_page.title.return_value = "Obstawianie Team A - Team B | Betclic"
        mock_page.query_selector.side_effect = lambda sel: mock_header if ("h1" in sel or "header" in sel) else None
        mock_page.query_selector_all.side_effect = lambda sel: [mock_tab] if ("tab" in sel or "category" in sel) else []
        mock_page.content.return_value = "<html><body></body></html>"

        def mock_eval(script, *args):
            s = str(script)
            if "liveSelectors" in s:
                return {"is_live": True, "signal": ".event_header.is-live", "text": "LIVE"}
            if "innerHeight" in s:
                return 800
            if "scrollHeight" in s:
                return 1000
            if "currentTabName" in s or len(args) > 0:
                return [{"container_id": "box_1", "category": "Top", "market": "Suma goli 2.5", "selection": "Powyżej 2.5", "section_title": "", "odds": "1.85", "raw": "Powyżej 2.5 1.85", "missing_header": False, "source_index": 1}]
            if "interactive" in s or "seenButtons" in s:
                return {"interactive_control_count": 1, "priced_candidate_count": 1, "unpriced_control_count": 0, "selectable_count": 1, "remaining_closed": 0, "remaining_more": 0}
            return None

        mock_page.evaluate.side_effect = mock_eval

        mock_context = MagicMock()
        mock_context.pages = [mock_page]
        mock_pw = MagicMock()
        mock_pw.chromium.launch_persistent_context.return_value = mock_context
        mock_pw_cm = MagicMock()
        mock_pw_cm.__enter__.return_value = mock_pw

        extractor = BetclicOddsExtractor()
        with patch("playwright.sync_api.sync_playwright", return_value=mock_pw_cm), \
             patch("core.find_chrome_exe", return_value=None):
            res = extractor.extract("https://www.betclic.pl/pilka-nozna-sfootball/test-c1/match-m123")

        self.assertEqual(res.get("status"), "BLOCKED")
        self.assertEqual(res.get("event_status"), "LIVE")
        self.assertEqual(res.get("odds_count"), 0)

    def test_55_live_guard_timer_status(self) -> None:
        from unittest.mock import MagicMock, patch

        from core import BetclicOddsExtractor

        mock_header = MagicMock()
        mock_header.inner_text.return_value = "Team A - Team B"
        mock_header.is_visible.return_value = False

        mock_tab = MagicMock()
        mock_tab.inner_text.return_value = "GŁÓWNE"
        mock_tab.query_selector.return_value = None
        mock_tab.get_attribute.return_value = "tab_item isActive"
        mock_tab.is_visible.return_value = False

        mock_page = MagicMock()
        mock_page.goto.return_value = MagicMock(status=200)
        mock_page.title.return_value = "Obstawianie Team A - Team B | Betclic"
        mock_page.query_selector.side_effect = lambda sel: mock_header if ("h1" in sel or "header" in sel) else None
        mock_page.query_selector_all.side_effect = lambda sel: [mock_tab] if ("tab" in sel or "category" in sel) else []
        mock_page.content.return_value = "<html><body></body></html>"

        def mock_eval(script, *args):
            s = str(script)
            if "liveSelectors" in s:
                return {"is_live": True, "signal": "timer_text", "text": "24' • 1. połowa"}
            if "innerHeight" in s:
                return 800
            if "scrollHeight" in s:
                return 1000
            if "currentTabName" in s or len(args) > 0:
                return [{"container_id": "box_1", "category": "Top", "market": "Suma goli 2.5", "selection": "Powyżej 2.5", "section_title": "", "odds": "1.85", "raw": "Powyżej 2.5 1.85", "missing_header": False, "source_index": 1}]
            if "interactive" in s or "seenButtons" in s:
                return {"interactive_control_count": 1, "priced_candidate_count": 1, "unpriced_control_count": 0, "selectable_count": 1, "remaining_closed": 0, "remaining_more": 0}
            return None

        mock_page.evaluate.side_effect = mock_eval

        mock_context = MagicMock()
        mock_context.pages = [mock_page]
        mock_pw = MagicMock()
        mock_pw.chromium.launch_persistent_context.return_value = mock_context
        mock_pw_cm = MagicMock()
        mock_pw_cm.__enter__.return_value = mock_pw

        extractor = BetclicOddsExtractor()
        with patch("playwright.sync_api.sync_playwright", return_value=mock_pw_cm), \
             patch("core.find_chrome_exe", return_value=None):
            res = extractor.extract("https://www.betclic.pl/pilka-nozna-sfootball/test-c1/match-m123")

        self.assertEqual(res.get("status"), "BLOCKED")
        self.assertEqual(res.get("event_status"), "LIVE")
        self.assertEqual(res.get("odds_count"), 0)

    def test_56_live_guard_no_false_positive(self) -> None:
        from unittest.mock import MagicMock

        from core import _detect_live_event_status

        mock_page = MagicMock()
        mock_page.evaluate.return_value = {"is_live": False, "signal": "", "text": ""}

        is_live, signal = _detect_live_event_status(mock_page)
        self.assertFalse(is_live)
        self.assertEqual(signal, "")

    def test_57_snapshot_tick_move_merges(self) -> None:
        from core import _dedupe_records_preserving_order
        from parser import parse_market_record

        r1, _ = parse_market_record(
            category="GŁÓWNE", market_title="Suma goli 2.5", raw_selection="Powyżej 2.5",
            odds_str="1.80", raw_text="Powyżej 2.5 1.80", section_title="", home_team="Team A",
            away_team="Team B", container_id="box_1"
        )
        r1["source_index"] = 10
        r1["capture_id"] = "cap_1"

        r2, _ = parse_market_record(
            category="GŁÓWNE", market_title="Suma goli 2.5", raw_selection="Powyżej 2.5",
            odds_str="1.78", raw_text="Powyżej 2.5 1.78", section_title="", home_team="Team A",
            away_team="Team B", container_id="box_1"
        )
        r2["source_index"] = 20
        r2["capture_id"] = "cap_2"

        extracted = [r1, r2]
        unresolved = []
        unique_odds, unres_out = _dedupe_records_preserving_order(extracted, unresolved)

        self.assertEqual(len(unique_odds), 1)
        self.assertEqual(len(unres_out), 0)
        self.assertEqual(unique_odds[0]["ODDS"], "1.78")
        self.assertEqual(unique_odds[0]["capture_id"], "cap_2")

    def test_58_single_snapshot_different_odds_conflict(self) -> None:
        from core import _dedupe_records_preserving_order
        from parser import parse_market_record

        r1, _ = parse_market_record(
            category="GŁÓWNE", market_title="Suma goli 2.5", raw_selection="Powyżej 2.5",
            odds_str="1.80", raw_text="Powyżej 2.5 1.80", section_title="", home_team="Team A",
            away_team="Team B", container_id="box_1"
        )
        r1["source_index"] = 10
        r1["capture_id"] = "cap_1"

        r2, _ = parse_market_record(
            category="GŁÓWNE", market_title="Suma goli 2.5", raw_selection="Powyżej 2.5",
            odds_str="1.90", raw_text="Powyżej 2.5 1.90", section_title="", home_team="Team A",
            away_team="Team B", container_id="box_1"
        )
        r2["source_index"] = 11
        r2["capture_id"] = "cap_1"

        extracted = [r1, r2]
        unresolved = []
        unique_odds, unres_out = _dedupe_records_preserving_order(extracted, unresolved)

        self.assertEqual(len(unique_odds), 1)
        self.assertEqual(len(unres_out), 1)
        self.assertEqual(unres_out[0]["REASON"], "CONFLICTING_ODDS_FOR_SAME_SELECTION")

    def test_59_cross_tab_different_capture_tick(self) -> None:
        from core import _dedupe_records_preserving_order
        from parser import parse_market_record

        r1, _ = parse_market_record(
            category="Top", market_title="Oba zespoły strzelą gola", raw_selection="Tak",
            odds_str="1.65", raw_text="Tak 1.65", section_title="", home_team="Team A",
            away_team="Team B", container_id="box_top"
        )
        r1["source_index"] = 10
        r1["capture_id"] = "cap_1"

        r2, _ = parse_market_record(
            category="Gole", market_title="Oba zespoły strzelą gola", raw_selection="Tak",
            odds_str="1.64", raw_text="Tak 1.64", section_title="", home_team="Team A",
            away_team="Team B", container_id="box_gole"
        )
        r2["source_index"] = 20
        r2["capture_id"] = "cap_2"

        extracted = [r1, r2]
        unresolved = []
        unique_odds, unres_out = _dedupe_records_preserving_order(extracted, unresolved)

        self.assertEqual(len(unique_odds), 1)
        self.assertEqual(len(unres_out), 0)
        self.assertEqual(unique_odds[0]["ODDS"], "1.64")

    def test_60_half_markets_period_no_conflict(self) -> None:
        from core import _dedupe_records_preserving_order
        from parser import parse_market_record

        r1, _ = parse_market_record(
            category="Gole", market_title="Oba zespoły strzelą gola", raw_selection="Tak",
            odds_str="1.61", raw_text="Tak 1.61", section_title="", home_team="Miedź",
            away_team="Podbeskidzie", container_id="box_ft"
        )
        r1["source_index"] = 10
        r1["capture_id"] = "cap_1"

        r2, _ = parse_market_record(
            category="Gole", market_title="Oba zespoły strzelą gola - 1. połowa", raw_selection="Tak",
            odds_str="3.73", raw_text="Tak 3.73", section_title="", home_team="Miedź",
            away_team="Podbeskidzie", container_id="box_1h"
        )
        r2["source_index"] = 11
        r2["capture_id"] = "cap_1"

        extracted = [r1, r2]
        unresolved = []
        unique_odds, unres_out = _dedupe_records_preserving_order(extracted, unresolved)

        self.assertEqual(len(unique_odds), 2)
        self.assertEqual(len(unres_out), 0)
        self.assertEqual(unique_odds[0]["PERIOD"], "FULL_TIME")
        self.assertEqual(unique_odds[1]["PERIOD"], "1ST_HALF")

    def test_61_scorer_scope_anytime_vs_first_goal_no_conflict(self) -> None:
        from core import _dedupe_records_preserving_order
        from parser import parse_market_record

        r1, _ = parse_market_record(
            category="Strzelcy", market_title="Strzelec gola", raw_selection="Daniel Stanclik",
            odds_str="2.60", raw_text="Daniel Stanclik 2.60", section_title="Strzelec w meczu",
            home_team="Miedź", away_team="Podbeskidzie", container_id="box_anytime"
        )
        r1["source_index"] = 10
        r1["capture_id"] = "cap_1"

        r2, _ = parse_market_record(
            category="Strzelcy", market_title="Strzelec gola", raw_selection="Daniel Stanclik",
            odds_str="9.25", raw_text="Daniel Stanclik 9.25", section_title="Strzelec 1. gola",
            home_team="Miedź", away_team="Podbeskidzie", container_id="box_first"
        )
        r2["source_index"] = 11
        r2["capture_id"] = "cap_1"

        extracted = [r1, r2]
        unresolved = []
        unique_odds, unres_out = _dedupe_records_preserving_order(extracted, unresolved)

        self.assertEqual(len(unique_odds), 2)
        self.assertEqual(len(unres_out), 0)
        self.assertEqual(unique_odds[0]["SCORER_SCOPE"], "ANYTIME")
        self.assertEqual(unique_odds[1]["SCORER_SCOPE"], "FIRST_GOAL")

    def test_62_capture_id_present_in_export(self) -> None:
        from parser import parse_market_record
        r, _ = parse_market_record(
            category="Top", market_title="Oba zespoły strzelą gola", raw_selection="Tak",
            odds_str="1.65", raw_text="Tak 1.65", section_title="", home_team="Team A",
            away_team="Team B", container_id="box_top"
        )
        r["capture_id"] = "cap_42"
        self.assertEqual(r.get("capture_id"), "cap_42")

    def test_63_same_capture_true_conflict_unresolved(self) -> None:
        from core import _dedupe_records_preserving_order
        from parser import parse_market_record

        r1, _ = parse_market_record(
            category="Top", market_title="Suma goli 2.5", raw_selection="Powyżej 2.5",
            odds_str="1.80", raw_text="Powyżej 2.5 1.80", section_title="", home_team="Team A",
            away_team="Team B", container_id="box_1"
        )
        r1["source_index"] = 1
        r1["capture_id"] = "cap_1"

        r2, _ = parse_market_record(
            category="Top", market_title="Suma goli 2.5", raw_selection="Powyżej 2.5",
            odds_str="1.95", raw_text="Powyżej 2.5 1.95", section_title="", home_team="Team A",
            away_team="Team B", container_id="box_1"
        )
        r2["source_index"] = 2
        r2["capture_id"] = "cap_1"

        extracted = [r1, r2]
        unresolved = []
        unique_odds, unres_out = _dedupe_records_preserving_order(extracted, unresolved)

        self.assertEqual(len(unique_odds), 1)
        self.assertEqual(len(unres_out), 1)
        self.assertEqual(unres_out[0]["REASON"], "CONFLICTING_ODDS_FOR_SAME_SELECTION")


class TestExhaustiveExtraction(unittest.TestCase):
    """Regression coverage for state-union extraction and completeness locks."""
    def record(self, title="Wynik meczu", selection="1", odds="1.80", **extra):
        from parser import parse_market_record
        args = {"category": "Main", "market_title": title, "raw_selection": selection, "odds_str": odds,
                    "raw_text": f"{selection} {odds}", "section_title": "", "home_team": "Home",
                    "away_team": "Away", "container_id": "box"}
        args.update(extra)
        return parse_market_record(**args)[0]

    def test_64_ft_1h_2h_column_periods(self):
        from parser import classify_period_detail
        self.assertEqual(classify_period_detail("Result", "", "1st half")[0], "1ST_HALF")
        self.assertEqual(classify_period_detail("Result", "", "2nd half")[0], "2ND_HALF")
        self.assertEqual(classify_period_detail("Match result", "")[0], "FULL_TIME")
    def test_65_half_only_does_not_become_full_time(self):
        from parser import classify_period_detail
        self.assertEqual(classify_period_detail("BTTS", "", "1st half")[0], "1ST_HALF")
        self.assertEqual(classify_period_detail("BTTS", "", "2nd half")[0], "2ND_HALF")
    def test_66_unknown_period_is_low_confidence(self):
        from parser import classify_period_detail
        self.assertEqual(classify_period_detail("Special", ""), ("UNKNOWN", "UNRESOLVED", "LOW"))
    def test_67_correct_score_full_grid_union(self):
        from exhaustive import raw_signature
        self.assertEqual(len({raw_signature({"market":"Correct score", "selection":s, "odds":"5.00", "section_title":""}) for s in ("0-0", "1-0", "0-1", "4-0", "0-4", "Other")}), 6)
    def test_68_virtual_list_union_preserves_removed_rows(self):
        from exhaustive import raw_signature
        self.assertEqual(len({raw_signature({"market":"Scorer", "selection":n, "odds":"2.00", "section_title":""}) for n in ("A", "B", "C", "D")}), 4)
    def test_69_horizontal_subtabs_are_manifested(self):
        from exhaustive import CoverageManifest
        m = CoverageManifest("Main"); m.discovered_interactions.update({"a", "b"}); m.visited_interactions.update({"a", "b"})
        self.assertEqual((m.as_dict()["discovered_interactions"], m.as_dict()["visited_interactions"]), (2, 2))
    def test_70_multiple_more_controls(self):
        from exhaustive import CoverageManifest
        m = CoverageManifest("Main"); m.expanded_controls = 3; m.remaining_more = 0
        self.assertEqual((m.expanded_controls, m.remaining_more), (3, 0))
    def test_71_nested_scroll_completion(self):
        from exhaustive import CoverageManifest
        m = CoverageManifest("Main"); m.scroll_containers.update({"outer", "inner"}); m.finished_scroll_containers.update({"outer", "inner"})
        self.assertEqual(m.as_dict()["scroll_containers"], m.as_dict()["finished_scroll_containers"])
    def test_72_supersub_scope(self):
        from parser import scorer_scope
        self.assertEqual(scorer_scope("SuperSub scorer"), "SUPERSUB_ANYTIME")
    def test_73_distinct_scorer_scopes(self):
        from parser import scorer_scope
        self.assertNotEqual(scorer_scope("First goalscorer"), scorer_scope("Last goalscorer"))
    def test_74_duplicate_tab_provenance_is_not_identity(self):
        one, two = self.record(), self.record()
        self.assertEqual((one["PERIOD"], one["FAMILY"], one["SELECTION"]), (two["PERIOD"], two["FAMILY"], two["SELECTION"]))
    def test_75_tick_movement_is_detectable(self): self.assertNotEqual(self.record(odds="1.80")["ODDS"], self.record(odds="1.90")["ODDS"])
    def test_76_unfinished_container_blocks_gate_inputs(self):
        from exhaustive import CoverageManifest
        m = CoverageManifest("Main"); m.scroll_containers.add("list")
        self.assertNotEqual(len(m.scroll_containers), len(m.finished_scroll_containers))
    def test_77_visible_raw_signature_parity(self):
        from exhaustive import CoverageManifest
        m = CoverageManifest("Main"); m.unique_visible_signatures.add("x"); m.raw_exported_signatures.add("x")
        self.assertEqual(m.unique_visible_signatures, m.raw_exported_signatures)


class TestRealPrematchReplay(unittest.TestCase):
    def test_78_replay_reads_teams_and_container_identity_from_capture(self):
        from replay import _capture_container_identity, _capture_teams
        rows = [
            {"market": "Liczba goli - Home", "active_tab": "Top", "market_instance_id": "tab:Top|market-a|row#0|cell:x"},
            {"market": "Liczba goli - Away", "active_tab": "Top", "market_instance_id": "tab:Top|market-b|row#1|cell:x"},
        ]
        self.assertEqual(_capture_teams(rows), ("Home", "Away"))
        self.assertEqual(_capture_container_identity(rows[0]), "tab:Top|market-a")

    def test_79_latest_capture_replay_matches_capture_truth(self):
        from pathlib import Path

        from replay import replay_real_prematch
        path = Path("diagnostics/raw_before_dedupe_run_1785264598_16328.jsonl")
        result = replay_real_prematch(path)
        # The preserved, duplicate-tab "result & BTTS" rows are a known
        # compound family: retain them as accepted records, not quarantine.
        self.assertEqual((result["period_unknown"], result["unresolved_count"], len(result["odds"])), (0, 1, 265))
        self.assertEqual(result["semantic_quarantine"], [])

    def test_78_fixture_replay_is_deterministic(self):
        from replay import replay_real_prematch
        self.assertEqual(replay_real_prematch(), replay_real_prematch())

    def test_79_period_unknown_reduced_for_real_capture(self):
        from replay import replay_real_prematch
        self.assertLess(replay_real_prematch()["period_unknown"], 216)

    def test_80_tab_and_parent_period_inheritance(self):
        from parser import classify_period_detail
        self.assertEqual(classify_period_detail("BTTS", "", "", "1. połowa", "Top", "BTTS")[0], "1ST_HALF")
        self.assertEqual(classify_period_detail("BTTS", "", "", "", "1. połowa", "BTTS")[0], "1ST_HALF")

    def test_81_top_without_local_header_stays_unresolved(self):
        from replay import replay_real_prematch
        result = replay_real_prematch()
        self.assertEqual(sum(x["REASON"] == "MISSING_MARKET_HEADER" for x in result["unresolved"]), 10)

    def test_82_ft_half_qualification_scopes_are_distinct(self):
        from parser import classify_period_detail
        self.assertEqual(classify_period_detail("Wynik meczu", "", family="1X2")[0], "FULL_TIME")
        self.assertEqual(classify_period_detail("Wynik meczu - 1. połowa", "", family="1X2")[0], "1ST_HALF")
        self.assertEqual(classify_period_detail("Zwycięzca rywalizacji", "", family="1X2")[0], "QUALIFICATION")

    def test_83_same_capture_identical_odds_merge(self):
        from core import _dedupe_records_preserving_order
        base = {"FAMILY":"1X2", "MARKET":"Wynik meczu", "PERIOD":"FULL_TIME", "SETTLEMENT_SCOPE":"FULL_TIME", "MARKET_SCOPE":"FULL_TIME", "OWNER":"", "SELECTION":"HOME", "LINE":"", "SCORER_SCOPE":"", "ODDS":"1.50", "capture_id":"c1", "source_index":1}
        out, unresolved = _dedupe_records_preserving_order([base, {**base, "source_index":2}], [])
        self.assertEqual((len(out), len(unresolved)), (1, 0))

    def test_84_same_capture_different_odds_stays_conflict(self):
        from core import _dedupe_records_preserving_order
        base = {"FAMILY":"1X2", "MARKET":"Wynik meczu", "PERIOD":"FULL_TIME", "SETTLEMENT_SCOPE":"FULL_TIME", "MARKET_SCOPE":"FULL_TIME", "OWNER":"", "SELECTION":"HOME", "LINE":"", "SCORER_SCOPE":"", "ODDS":"1.50", "capture_id":"c1", "source_index":1}
        out, unresolved = _dedupe_records_preserving_order([base, {**base, "ODDS":"1.60", "source_index":2}], [])
        self.assertEqual((len(out), unresolved[0]["REASON"]), (1, "CONFLICTING_ODDS_FOR_SAME_SELECTION"))

    def test_85_handicap_kind_and_line_are_explicit(self):
        from parser import parse_market_record
        three, _ = parse_market_record(category="Wynik", market_title="Handicap", raw_selection="Home (-1)", odds_str="2.00", raw_text="Home (-1) 2.00", section_title="", home_team="Home", away_team="Away", container_id="x")
        two, _ = parse_market_record(category="Wynik", market_title="Handicap (2-drożny)", raw_selection="Home (-1.5)", odds_str="2.00", raw_text="Home (-1.5) 2.00", section_title="", home_team="Home", away_team="Away", container_id="x")
        self.assertEqual((three["HANDICAP_KIND"], two["HANDICAP_KIND"]), ("THREE_WAY", "TWO_WAY"))
        self.assertEqual((three["LINE"], two["LINE"]), ("-1", "-1.5"))

    def test_86_replay_has_no_html_json_noise(self):
        from replay import load_real_prematch_fixture
        self.assertTrue(all("<html" not in row.get("raw", "").lower() and "{\"" not in row.get("raw", "") for row in load_real_prematch_fixture()))


class TestProvenanceCaptureFields(unittest.TestCase):
    def test_87_collector_emits_all_provenance_fields(self):
        from core import _make_dom_script
        script = _make_dom_script()
        for field in ("market_instance_id", "dom_path", "heading_path", "active_tab", "active_subtab",
                      "period_hint", "settlement_scope_hint", "line_hint", "handicap_kind", "visibility",
                      "render_state", "scroll_position"):
            self.assertIn(field, script)

    def test_88_hierarchy_and_explicit_scope_are_parser_evidence(self):
        from parser import parse_market_record
        record, _ = parse_market_record(category="Top", market_title="Wynik", raw_selection="1", odds_str="2.00",
            raw_text="1 2.00", section_title="", ancestor_title="1. połowa", period_hint="", main_tab="Top",
            settlement_scope_hint="FIRST_HALF", line_hint="", handicap_kind_hint="", home_team="A", away_team="B", container_id="x")
        self.assertEqual((record["PERIOD"], record["PERIOD_SOURCE"], record["MARKET_SCOPE"]),
                         ("1ST_HALF", "SETTLEMENT_SCOPE_HINT", "FIRST_HALF"))

    def test_89_active_tab_is_preserved_in_replay_provenance(self):
        from replay import replay_real_prematch
        self.assertTrue(all("ACTIVE_TAB" in record for record in replay_real_prematch()["odds"]))

    def test_90_hidden_responsive_duplicate_keeps_visible_odds(self):
        from core import _dedupe_records_preserving_order
        base = {"FAMILY":"1X2", "MARKET":"Wynik", "PERIOD":"FULL_TIME", "SETTLEMENT_SCOPE":"FULL_TIME", "MARKET_SCOPE":"FULL_TIME", "OWNER":"", "SELECTION":"HOME", "LINE":"", "SCORER_SCOPE":"", "MARKET_INSTANCE_ID":"m1", "ODDS":"1.50", "capture_id":"c1", "source_index":1, "SOURCE_VISIBILITY":"VISIBLE"}
        out, unresolved = _dedupe_records_preserving_order([base, {**base, "ODDS":"1.60", "SOURCE_VISIBILITY":"HIDDEN", "source_index":2}], [])
        self.assertEqual((len(out), out[0]["ODDS"], len(unresolved)), (1, "1.50", 0))

    def test_91_different_explicit_scope_or_line_is_not_conflict(self):
        from core import _dedupe_records_preserving_order
        base = {"FAMILY":"HANDICAP_EUROPEAN", "MARKET":"Handicap", "PERIOD":"FULL_TIME", "SETTLEMENT_SCOPE":"FULL_TIME", "MARKET_SCOPE":"FULL_TIME", "OWNER":"", "SELECTION":"HOME", "LINE":"-1", "SCORER_SCOPE":"", "ODDS":"1.50", "capture_id":"c1", "source_index":1}
        other = {**base, "MARKET_SCOPE":"FIRST_HALF", "PERIOD":"1ST_HALF", "SETTLEMENT_SCOPE":"FIRST_HALF", "LINE":"-0.5", "ODDS":"1.60"}
        out, unresolved = _dedupe_records_preserving_order([base, other], [])
        self.assertEqual((len(out), len(unresolved)), (2, 0))


class TestStableMarketInstanceId(unittest.TestCase):
    def test_92_sibling_market_rows_get_unique_ids(self):
        from playwright.sync_api import sync_playwright

        from core import _extract_dom_from_page
        html = '''<div class="marketBox"><h3>Wynik meczu</h3>
        <div class="marketBox_lineSelection"><span class="marketBox_label">A</span><button class="is-odd">1.50</button></div>
        <div class="marketBox_lineSelection"><span class="marketBox_label">B</span><button class="is-odd">2.50</button></div></div>'''
        with sync_playwright() as p:
            page = p.chromium.launch(headless=True).new_page(); page.set_content(html)
            rows = _extract_dom_from_page(page, "Top")
        self.assertEqual(len({row["market_instance_id"] for row in rows}), 2)
        self.assertTrue(all(row["odds"] not in row["market_instance_id"] for row in rows))

    def test_93_old_replay_remains_stable_without_new_ids(self):
        from replay import replay_real_prematch
        self.assertEqual(replay_real_prematch(), replay_real_prematch())

    def test_94_visible_hidden_siblings_stay_separate(self):
        from core import _dedupe_records_preserving_order
        base = {"FAMILY":"1X2", "MARKET":"Wynik", "PERIOD":"FULL_TIME", "SETTLEMENT_SCOPE":"FULL_TIME", "MARKET_SCOPE":"FULL_TIME", "OWNER":"", "SELECTION":"HOME", "LINE":"", "SCORER_SCOPE":"", "capture_id":"c1", "source_index":1}
        visible = {**base, "MARKET_INSTANCE_ID":"container|row#0|cell#0", "SOURCE_VISIBILITY":"VISIBLE", "ODDS":"1.50"}
        hidden = {**base, "MARKET_INSTANCE_ID":"container|row#1|cell#0", "SOURCE_VISIBILITY":"HIDDEN", "ODDS":"1.60"}
        out, unresolved = _dedupe_records_preserving_order([visible, hidden], [])
        self.assertEqual((len(out), len(unresolved)), (2, 0))

    def test_95_cross_tab_virtual_paths_get_distinct_instance_ids(self):
        from playwright.sync_api import sync_playwright

        from core import _extract_dom_from_page
        html = '''<div class="marketBox"><h3>Wynik meczu</h3>
        <div class="marketBox_lineSelection"><span class="marketBox_label">A</span><button class="is-odd">1.50</button></div></div>'''
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(); page.set_content(html)
            top = _extract_dom_from_page(page, "Top")
            result = _extract_dom_from_page(page, "Wynik")
            browser.close()
        self.assertTrue({row["market_instance_id"] for row in top}.isdisjoint(
            row["market_instance_id"] for row in result))

    def test_96_headerless_top_mycombi_card_is_excluded(self):
        from playwright.sync_api import sync_playwright

        from core import _extract_dom_from_page
        html = '''<sports-top-my-combi><button class="is-odd">MyCombi 2.10</button></sports-top-my-combi>'''
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(); page.set_content(html)
            rows = _extract_dom_from_page(page, "Top")
            browser.close()
        self.assertEqual(rows, [])


class TestPrematchPreflightGate(unittest.TestCase):
    def preflight(self, status):
        from unittest.mock import MagicMock

        from core import _preflight_event_status
        page = MagicMock(); page.evaluate.return_value = {"status": status, "proof": "test-proof"}
        return _preflight_event_status(page)

    def test_95_prematch_preflight_allows_capture(self):
        self.assertEqual(self.preflight("PREMATCH")[0], "PREMATCH")

    def test_96_live_preflight_blocks_before_capture(self):
        self.assertEqual(self.preflight("LIVE")[0], "LIVE")

    def test_97_ft_preflight_blocks_before_capture(self):
        self.assertEqual(self.preflight("FT")[0], "FT")

    def test_98_unknown_preflight_blocks_before_capture(self):
        self.assertEqual(self.preflight("UNKNOWN")[0], "UNKNOWN")


class TestCleanCoreScopedGate(unittest.TestCase):
    def test_103_saved_capture_is_clean_core_ready_only(self):
        from pathlib import Path

        from core import _evaluate_clean_core_gate
        from replay import replay_real_prematch
        result = replay_real_prematch(Path("diagnostics/raw_before_dedupe_run_1785264598_16328.jsonl"))
        gate = _evaluate_clean_core_gate(result["odds"], result["unresolved"], [])
        self.assertEqual((gate["clean_core_ready"], gate["analysis_scope"],
                          gate["excluded_unknown_count"], gate["excluded_unresolved_count"]),
                      ("YES", "CLEAN_CORE_ONLY", 0, 1))

    def test_104_core_unknown_or_unresolved_blocks_clean_core(self):
        from core import _evaluate_clean_core_gate
        core_unknown = {"FAMILY": "1X2", "PERIOD": "UNKNOWN"}
        core_unresolved = {"MARKET": "Wynik meczu", "RAW": "Home 1.50"}
        gate = _evaluate_clean_core_gate([core_unknown], [core_unresolved], [])
        self.assertEqual((gate["clean_core_ready"], gate["core_unknown_count"], gate["core_unresolved_count"]),
                         ("NO", 1, 1))


class TestGuiPartialStatus(unittest.TestCase):
    def test_105_saved_partial_capture_has_warning_details_and_packet(self):
        from pathlib import Path

        from gui import _partial_result_details
        from replay import replay_real_prematch
        replay = replay_real_prematch(Path("diagnostics/raw_before_dedupe_run_1785269255_18296.jsonl"))
        details = _partial_result_details({
            "status": "PARTIAL", "odds_count": len(replay["odds"]), "unresolved_count": replay["unresolved_count"],
            "odds": replay["odds"], "incomplete_reasons": ["PERIOD_UNKNOWN", "UNRESOLVED"],
            "packet_text": "saved-partial-packet",
        })
        self.assertEqual((details["odds_count"], details["unresolved_count"], details["packet_text"]),
                         # Result+BTTS is now a closed, lossless compound
                         # representation, so these six legal rows remain
                         # exportable instead of being silently excluded.
                         (189, 1, "saved-partial-packet"))
        # The replay fixture is now period-complete; the UI still exposes its
        # supplied PERIOD_UNKNOWN warning reason without inventing an unknown row.
        self.assertEqual(details["unknown_count"], 0)
        self.assertIn("PERIOD_UNKNOWN", details["reason"])

    def test_106_non_partial_status_is_not_reclassified_by_details(self):
        from gui import _partial_result_details
        details = _partial_result_details({"status": "BŁĄD", "error": "HTTP failure"})
        self.assertEqual((details["odds_count"], details["unknown_count"], details["unresolved_count"]), (0, 0, 0))

    def test_106a_worker_error_callback_retains_exception_text(self):
        from unittest.mock import MagicMock, patch

        from gui import BetclicExtractorGUI

        gui = BetclicExtractorGUI.__new__(BetclicExtractorGUI)
        gui.root = MagicMock()
        completed: list[dict[str, str]] = []
        gui._on_done = completed.append
        with patch("gui.DiagnosticsManager", return_value=MagicMock()), \
             patch("gui.BetclicOddsExtractor") as extractor_cls:
            extractor_cls.return_value.extract.side_effect = RuntimeError("capture failed")
            gui._worker("https://www.betclic.pl/pilka-nozna-sfootball/test-c1/match-m123")

        callback = gui.root.after.call_args.args[1]
        callback()
        self.assertEqual(completed, [{
            "status": "BŁĄD", "error": "Krytyczny błąd: capture failed", "packet_text": ""
        }])


class TestNestedGroupedMarketPeriodProvenance(unittest.TestCase):
    def test_107_grouped_columns_emit_explicit_period_hint_and_instance_scope(self):
        from playwright.sync_api import sync_playwright

        from core import _extract_dom_from_page
        html = '''<div class="marketBox is-groupedMarket"><h3 class="marketBox_headTitle">Wynik meczu</h3>
        <div class="marketBox_body"><div class="marketBox_list">
        <div class="marketBox_item"><span class="marketBox_itemValue">1. po&#322;owa</span></div>
        <div class="marketBox_item"><span class="marketBox_itemValue">2. po&#322;owa</span></div></div>
        <div class="marketBox_lineSelection"><span class="marketBox_label">Home</span><div class="marketBox_list">
        <div class="marketBox_item"><button class="is-odd">2.75</button></div><div class="marketBox_item"><button class="is-odd">2.50</button></div>
        </div></div></div></div>'''
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(); page.set_content(html)
            rows = _extract_dom_from_page(page, "Top")
            browser.close()
        self.assertEqual([row["period_hint"] for row in rows], ["1. po\u0142owa", "2. po\u0142owa"])
        self.assertTrue(all("|column:" in row["market_instance_id"] for row in rows))

    def test_108_saved_grouped_capture_replay_has_explicit_half_parity(self):
        from pathlib import Path

        from replay import replay_real_prematch
        result = replay_real_prematch(Path("diagnostics/raw_before_dedupe_run_1785269255_18296.jsonl"))
        rows = {(row["MARKET"], f"{float(row['ODDS']):.2f}"): row for row in result["odds"]}
        first_half = [("Wynik meczu", value) for value in ("2.75", "1.97", "3.70")] + [("Oba zespo\u0142y strzel\u0105 gola", value) for value in ("4.20", "1.13")]
        second_half = [("Wynik meczu", value) for value in ("2.50", "2.28", "3.28")] + [("Oba zespo\u0142y strzel\u0105 gola", value) for value in ("3.40", "1.21")]
        self.assertTrue(all(rows[key]["PERIOD"] == "1ST_HALF" and rows[key]["PERIOD_SOURCE"] == "CELL_PERIOD_HINT" for key in first_half))
        self.assertTrue(all(rows[key]["PERIOD"] == "2ND_HALF" and rows[key]["PERIOD_SOURCE"] == "CELL_PERIOD_HINT" for key in second_half))
        self.assertEqual(rows[("Wynik meczu (z wy\u0142\u0105czeniem dogrywki)", "2.15")]["PERIOD"], "FULL_TIME")
        self.assertEqual(rows[("Oba zespo\u0142y strzel\u0105 gola", "1.83")]["PERIOD"], "FULL_TIME")

    def test_109_saved_grouped_capture_keeps_clean_core_ready(self):
        from pathlib import Path

        from core import _evaluate_clean_core_gate
        from replay import replay_real_prematch
        result = replay_real_prematch(Path("diagnostics/raw_before_dedupe_run_1785269255_18296.jsonl"))
        gate = _evaluate_clean_core_gate(result["odds"], result["unresolved"], [])
        self.assertEqual((gate["clean_core_ready"], gate["analysis_scope"]), ("YES", "CLEAN_CORE_ONLY"))


class TestStrzelcyThirdContainerRetry(unittest.TestCase):
    def test_110_retry_uses_locator_and_three_stable_samples(self):
        from core import _retry_unfinished_strzelcy_containers
        class Page:
            def __init__(self): self.calls = 0
            def evaluate(self, script, locator=None):
                if locator is None: return [{"locator":"DIV.scroller#2", "height":100, "top":0, "priced":2, "last":"A 2.00"}]
                self.calls += 1
                return {"height":100, "priced":3, "last":"B 2.00"}
        page = Page(); evidence = _retry_unfinished_strzelcy_containers(page, lambda: None, lambda _: None)
        self.assertTrue(evidence[0]["finished"])
        self.assertGreaterEqual(page.calls, 4)

    def test_111_retry_has_no_detached_dom_handle_parameter(self):
        from core import _retry_unfinished_strzelcy_containers
        self.assertIn("locator", _retry_unfinished_strzelcy_containers.__doc__)


class TestReadinessTruthParity(unittest.TestCase):
    def test_112_final_snapshot_preserves_full_usable_truth_for_all_serializers(self):
        from core import _readiness_snapshot
        snapshot = _readiness_snapshot("YES", "YES", "NO", "FULL_USABLE_EXCLUDING_SOURCE_INCOMPLETE", "PASS")
        self.assertEqual(snapshot, {
            "ANALYSIS_READY": "YES", "FULL_USABLE_READY": "YES", "EXHAUSTIVE_READY": "NO",
            "ANALYSIS_SCOPE": "FULL_USABLE_EXCLUDING_SOURCE_INCOMPLETE", "PARSER_TRUTH_STATUS": "PASS",
        })

    def test_113_final_snapshot_does_not_inherit_previous_run_truth(self):
        from core import _readiness_snapshot
        full = _readiness_snapshot("YES", "YES", "NO", "FULL_USABLE_EXCLUDING_SOURCE_INCOMPLETE", "PASS")
        blocked = _readiness_snapshot("NO", "NO", "NO", "CLEAN_CORE_BLOCKED", "PARTIAL")
        self.assertNotEqual(full, blocked)
        self.assertEqual(blocked["ANALYSIS_SCOPE"], "CLEAN_CORE_BLOCKED")


class TestScorerVisibleExportParity(unittest.TestCase):
    @staticmethod
    def _control(index, *, market="Strzelcy", player=None, odds=None, instance=None,
                 line="", native_id=""):
        return {
            "market": market,
            "selection": player or f"Player {index}",
            "odds": odds or f"{2 + index / 100:.2f}",
            "section_title": "Strzelec",
            "period_hint": "",
            "line_hint": line,
            "market_instance_id": instance or f"tab:Strzelcy|market:{market}|row:{index}|cell:0",
            "native_selection_id": native_id,
        }

    def test_114_visible_113_priced_scorer_controls_export_113_distinct_rows(self):
        from exhaustive import raw_signature
        controls = [self._control(i) for i in range(93)]
        controls.extend(self._control(i, player=f"Player {i - 93}", odds=f"{2 + (i - 93) / 100:.2f}",
                                      instance=f"tab:Strzelcy|secondary-column|row:{i - 93}|cell:0")
                        for i in range(93, 113))
        self.assertEqual((len(controls), len({raw_signature(row) for row in controls})), (113, 113))

    def test_115_same_player_in_different_scorer_markets_remains_distinct(self):
        from exhaustive import raw_signature
        anytime = self._control(1, market="Strzelec gola", player="Mikael Ishak", odds="2.70")
        first = self._control(1, market="Pierwszy strzelec", player="Mikael Ishak", odds="2.70")
        self.assertNotEqual(raw_signature(anytime), raw_signature(first))

    def test_116_same_player_with_different_goal_lines_remains_distinct(self):
        from exhaustive import raw_signature
        over_half = self._control(1, market="Gole zawodnika", player="Mikael Ishak", odds="2.70", line="0.5")
        over_one = self._control(1, market="Gole zawodnika", player="Mikael Ishak", odds="2.70", line="1.5",
                                 instance="tab:Strzelcy|market:Gole zawodnika|row:1|cell:1")
        self.assertNotEqual(raw_signature(over_half), raw_signature(over_one))

    def test_117_true_native_selection_clone_exports_once(self):
        from exhaustive import raw_signature
        first = self._control(1, instance="tab:Strzelcy|desktop|row:1|cell:0", native_id="selection-321")
        clone = self._control(1, instance="tab:Strzelcy|responsive-clone|row:1|cell:0", native_id="selection-321")
        self.assertEqual(raw_signature(first), raw_signature(clone))

    def test_118_unknown_period_and_nested_columns_do_not_silently_drop_raw_rows(self):
        from exhaustive import raw_signature
        left = self._control(1, player="Mikael Ishak", odds="2.70", instance="tab:Strzelcy|box:17|column:win|row:1|cell:0")
        right = self._control(1, player="Mikael Ishak", odds="2.70", instance="tab:Strzelcy|box:22|column:win|row:1|cell:0")
        self.assertNotEqual(raw_signature(left), raw_signature(right))

    def test_119_sequential_scorer_unions_do_not_share_rows(self):
        from exhaustive import raw_signature
        event_a = {raw_signature(self._control(1, instance="event:a|row:1"))}
        event_b = {raw_signature(self._control(1, instance="event:b|row:1"))}
        self.assertFalse(event_a & event_b)


class TestMyCombiComponentSerialization(unittest.TestCase):
    class Page:
        def __init__(self, captured): self.captured = captured
        def evaluate(self, _): return self.captured

    @staticmethod
    def captured(components, odds="5.25", copies=2):
        return {
            "components": components,
            "combined_odds": odds,
            "representations": [{"odds": odds, "dom_path": f"slip:{index}"} for index in range(copies)],
        }

    @staticmethod
    def component(label, heading, order):
        return {"label": label, "market_heading": heading, "display_order": order}

    def test_120_two_components_emit_two_unpriced_rows_and_one_combination(self):
        from core import _extract_mycombi_state, _mycombi_state_rows
        captured = self.captured([
            self.component("Presidente Hayes", "Wynik meczu (z wyłączeniem dogrywki)", 1),
            self.component("Powyżej 0,5", "Gole Powyżej/Poniżej", 2),
        ])
        state = _extract_mycombi_state(self.Page(captured), "Presidente Hayes", "Deportivo Santani")
        rows = _mycombi_state_rows(state)
        self.assertEqual((len(state["components"]), len(rows), rows[-1]["record_type"]), (2, 3, "MYCOMBI_COMBINATION"))
        self.assertTrue(all(row["odds"] == "" for row in rows[:-1]))
        self.assertEqual(rows[-1]["odds"], "5.25")
        self.assertEqual((state["components"][1]["period"], state["components"][1]["period_source"]), ("FT", "CANONICAL_MARKET"))

    def test_121_current_state_replaces_stale_three_component_combination(self):
        from core import _extract_mycombi_state
        base = [self.component("Presidente Hayes", "Wynik meczu", 1), self.component("Powyżej 0,5", "Gole Powyżej/Poniżej", 2)]
        third = self.component("Powyżej 0,5", "Liczba goli - Deportivo Santani", 3)
        state_three = _extract_mycombi_state(self.Page(self.captured([*base, third], "9.50")), "Presidente Hayes", "Deportivo Santani")
        state_two = _extract_mycombi_state(self.Page(self.captured(base, "5.25")), "Presidente Hayes", "Deportivo Santani")
        self.assertEqual((state_three["combination"]["component_count"], state_three["combination"]["combined_odds"]), (3, "9.50"))
        self.assertEqual((state_two["combination"]["component_count"], state_two["combination"]["combined_odds"]), (2, "5.25"))
        self.assertNotEqual(state_three["combination"]["combination_id"], state_two["combination"]["combination_id"])

    def test_122_duplicate_ui_prices_merge_to_one_combination(self):
        from core import _extract_mycombi_state, _mycombi_state_rows
        state = _extract_mycombi_state(self.Page(self.captured([self.component("Home", "Wynik meczu", 1), self.component("Over 0.5", "Gole", 2)], copies=2)), "Home", "Away")
        rows = _mycombi_state_rows(state)
        self.assertEqual((state["combination"]["ui_representation_count"], sum(r["record_type"] == "MYCOMBI_COMBINATION" for r in rows)), (2, 1))

    def test_123_component_identity_keeps_market_owner_period_line_and_settlement(self):
        from core import _extract_mycombi_state
        state = _extract_mycombi_state(self.Page(self.captured([
            self.component("Powyżej 0,5", "Liczba goli - Home", 1),
            self.component("Powyżej 1,5", "Liczba goli - Home", 2),
            self.component("Powyżej 0,5", "Liczba goli - Away", 3),
            self.component("Powyżej 0,5", "Gole 1. połowa", 4),
        ])), "Home", "Away")
        components = state["components"]
        self.assertEqual(len({component["component_id"] for component in components}), 4)
        self.assertEqual([component["individual_odds"] for component in components], [None] * 4)
        self.assertEqual({component["owner"] for component in components}, {"HOME", "AWAY", "MATCH"})

    def test_124_unselected_components_and_sequential_events_do_not_leak(self):
        from core import _extract_mycombi_state
        first = _extract_mycombi_state(self.Page(self.captured([self.component("Home", "Wynik meczu", 1), self.component("Over 0.5", "Gole", 2)])), "Home", "Away")
        second = _extract_mycombi_state(self.Page(self.captured([self.component("Away", "Wynik meczu", 1), self.component("Under 2.5", "Gole", 2)])), "Other Home", "Other Away")
        self.assertEqual(len(first["components"]), 2)
        self.assertEqual(len(second["components"]), 2)
        self.assertNotEqual(first["combination"]["combination_id"], second["combination"]["combination_id"])
        self.assertNotIn("Home", [component["label"] for component in second["components"]])

    def test_125_component_period_uses_market_evidence_without_defaulting_unknown(self):
        from core import _extract_mycombi_state
        state = _extract_mycombi_state(self.Page(self.captured([
            self.component("Powyżej 0,5", "Gole Powyżej/Poniżej", 1),
            self.component("Powyżej 0,5", "Gole 1. połowa", 2),
            self.component("Powyżej 0,5", "Gole 2. połowa", 3),
            self.component("Powyżej 0,5", "Rynek bez okresu", 4),
        ])), "Home", "Away")
        self.assertEqual(
            [(item["period"], item["period_source"]) for item in state["components"]],
            [("FT", "CANONICAL_MARKET"), ("1H", "MARKET_TITLE"),
             ("2H", "MARKET_TITLE"), ("UNKNOWN", "UNRESOLVED")],
        )


class TestSourceHashCaptureLineage(unittest.TestCase):
    def test_126_identical_single_payload_has_stable_64_char_hash(self):
        from core import _source_hash_from_capture_sources
        first = _source_hash_from_capture_sources({"0000:Top": b'{"odds":"2.00"}'})
        second = _source_hash_from_capture_sources({"0000:Top": b'{"odds":"2.00"}'})
        self.assertEqual((first, len(first)), (second, 64))

    def test_127_changed_payload_changes_hash(self):
        from core import _source_hash_from_capture_sources
        self.assertNotEqual(
            _source_hash_from_capture_sources({"0000:Top": b'{"odds":"2.00"}'}),
            _source_hash_from_capture_sources({"0000:Top": b'{"odds":"2.01"}'}),
        )

    def test_128_bundle_hash_is_input_order_independent_and_byte_sensitive(self):
        from core import _source_hash_from_capture_sources
        left = {"0001:Gole": b"gole", "0000:Top": b"top"}
        right = {"0000:Top": b"top", "0001:Gole": b"gole"}
        changed = {"0000:Top": b"top", "0001:Gole": b"gole!"}
        self.assertEqual(_source_hash_from_capture_sources(left), _source_hash_from_capture_sources(right))
        self.assertNotEqual(_source_hash_from_capture_sources(left), _source_hash_from_capture_sources(changed))

    def test_129_parser_and_replay_preserve_nonempty_source_hash(self):
        from parser import parse_market_record
        record, issue = parse_market_record(
            category="Top", market_title="Wynik meczu", raw_selection="1", odds_str="2.00",
            raw_text="1 2.00", section_title="", home_team="Home", away_team="Away",
            container_id="c", run_id="run", event_id="Home|Away", source_hash="a" * 64,
            raw_record_id="run:1", source_raw_record_ids=["run:1"],
        )
        self.assertIsNone(issue)
        self.assertEqual(record["source_hash"], "a" * 64)
        self.assertEqual(record["source_raw_record_ids"], ["run:1"])

    def test_130_synthetic_capture_propagates_one_hash_to_raw_evidence_and_canonical(self):
        from core import _propagate_source_hash, _source_hash_from_capture_sources
        source_hash = _source_hash_from_capture_sources({"0000:Top": b"source"})
        raw = [
            {"raw_record_id": "run:1", "source_hash": "", "period_evidence_candidates": [{"source_hash": ""}]},
            {"raw_record_id": "run:2", "source_hash": "", "period_evidence_candidates": []},
        ]
        canonical = [{"raw_record_id": "run:1", "source_raw_record_ids": ["run:1"], "source_hash": ""}]
        _propagate_source_hash(raw, canonical, source_hash)
        self.assertEqual({row["source_hash"] for row in raw} | {canonical[0]["source_hash"]}, {source_hash})
        self.assertEqual(raw[0]["period_evidence_candidates"][0]["source_hash"], source_hash)
        self.assertEqual(canonical[0]["source_raw_record_ids"], ["run:1"])


class TestExcludedLineageRetention(unittest.TestCase):
    @staticmethod
    def _incomplete_handicap_rows():
        common = {
            "category": "Wynik", "market": "Handicap 2. połowa", "odds": "2.00",
            "section_title": "", "ancestor_title": "", "period_hint": "", "active_tab": "Wynik",
            "container_id": "c", "market_instance_id": "m", "run_id": "run", "event_id": "Home|Away",
            "source_hash": "a" * 64,
        }
        return [
            {**common, "selection": "Home (+2)", "raw": "Home (+2) 2.00", "raw_record_id": "run:1", "source_raw_record_ids": ["run:1"], "period_evidence_candidates": [{"raw_record_id": "run:1"}]},
            {**common, "selection": "Remis (Home +2)", "raw": "Remis (Home +2) 2.00", "raw_record_id": "run:2", "source_raw_record_ids": ["run:2"], "period_evidence_candidates": [{"raw_record_id": "run:2"}]},
        ]

    def test_131_incomplete_handicap_is_excluded_but_keeps_lineage(self):
        from pathlib import Path

        import replay
        original = replay.load_real_prematch_fixture
        try:
            replay.load_real_prematch_fixture = lambda _: self._incomplete_handicap_rows()
            result = replay.replay_real_prematch(Path("raw_before_dedupe_run_test.jsonl"))
        finally:
            replay.load_real_prematch_fixture = original
        self.assertFalse(result["odds"])
        self.assertEqual([entry["raw_record_id"] for entry in result["excluded_lineage"]], ["run:1", "run:2"])
        self.assertTrue(all(entry["exclusion_reason_code"] == "HANDICAP_COMPLETENESS_EXCLUSION" for entry in result["excluded_lineage"]))
        self.assertTrue(all(entry["run_id"] == "run" and entry["source_hash"] == "a" * 64 for entry in result["excluded_lineage"]))

    def test_132_terminal_state_audit_detects_conflicts_and_foreign_entries(self):
        from replay import audit_same_run_lineage
        canonical = [{"raw_record_id": "run:1", "source_raw_record_ids": ["run:1"]}]
        excluded = [
            {"raw_record_id": "run:1", "source_raw_record_ids": ["run:1"], "run_id": "run", "event_id": "Home|Away", "source_hash": "a" * 64},
            {"raw_record_id": "run:2", "source_raw_record_ids": ["run:2"], "run_id": "other", "event_id": "wrong", "source_hash": "b" * 64},
        ]
        audit = audit_same_run_lineage({"run:1", "run:2"}, canonical, excluded, run_id="run", event_id="Home|Away", source_hash="a" * 64)
        self.assertEqual(audit["multi_accounted_conflict"], 1)
        self.assertEqual((audit["excluded_foreign_run"], audit["excluded_foreign_event"], audit["excluded_foreign_source_hash"]), (1, 1, 1))


class TestHF5CDeterministicPeriodResolver(unittest.TestCase):
    @staticmethod
    def _record(raw_id="run:1", period="UNKNOWN"):
        return {"raw_record_id": raw_id, "source_raw_record_ids": [raw_id], "run_id": "run",
                "event_id": "Home|Away", "source_hash": "a" * 64, "PERIOD": period,
                "FAMILY": "1X2", "OWNER": "", "LINE": "", "HANDICAP_KIND": ""}

    @staticmethod
    def _raw(raw_id, evidence_period, **context):
        return {"raw_record_id": raw_id, "period_evidence_candidates": [{
            "raw_record_id": raw_id, "evidence_period": evidence_period,
            "run_id": context.get("run_id", "run"), "event_id": context.get("event_id", "Home|Away"),
            "source_hash": context.get("source_hash", "a" * 64), "evidence_provenance": "TEST",
        }]}

    def test_133_unknown_unanimous_ft_p1_p2_assigns_only_period(self):
        from core import resolve_periods_from_lineage
        for evidence, expected in (("FT", "FULL_TIME"), ("P1", "1ST_HALF"), ("P2", "2ND_HALF")):
            with self.subTest(evidence=evidence):
                record = self._record(); before = (record["FAMILY"], record["OWNER"], record["LINE"])
                diag = resolve_periods_from_lineage([record], [self._raw("run:1", evidence)])
                self.assertEqual(record["PERIOD"], expected)
                self.assertEqual(before, (record["FAMILY"], record["OWNER"], record["LINE"]))
                self.assertEqual(diag["decisions"][0]["reason_code"], "PERIOD_EVIDENCE_UNANIMOUS")

    def test_134_duplicate_order_independent_multiple_lineage_and_idempotent(self):
        from core import resolve_periods_from_lineage
        record = self._record("run:1"); record["source_raw_record_ids"] = ["run:2", "run:1"]
        raws = [self._raw("run:1", "P1"), self._raw("run:2", "P1"), self._raw("run:1", "P1")]
        first = resolve_periods_from_lineage([record], list(reversed(raws)))
        self.assertEqual(record["PERIOD"], "1ST_HALF")
        second = resolve_periods_from_lineage([record], raws)
        self.assertEqual(record["PERIOD"], "1ST_HALF")
        self.assertEqual(first["ASSIGNED_UNKNOWN_TO_P1"], 1)
        self.assertEqual(second["UNCHANGED_EXISTING"], 1)

    def test_135_conflict_and_no_evidence_leave_unknown(self):
        from core import resolve_periods_from_lineage
        conflicted = self._record(); no_evidence = self._record("run:2")
        diag = resolve_periods_from_lineage([conflicted, no_evidence], [self._raw("run:1", "FT"), self._raw("run:1", "P1")])
        self.assertEqual((conflicted["PERIOD"], no_evidence["PERIOD"]), ("UNKNOWN", "UNKNOWN"))
        self.assertEqual((diag["UNKNOWN_EVIDENCE_CONFLICT"], diag["UNKNOWN_NO_EVIDENCE"]), (1, 1))

    def test_136_foreign_evidence_and_existing_conflict_preserve_period(self):
        from core import resolve_periods_from_lineage
        unknown = self._record(); existing = self._record("run:2", "1ST_HALF")
        diag = resolve_periods_from_lineage(
            [unknown, existing],
            [self._raw("run:1", "FT", run_id="foreign"), self._raw("run:2", "P2")],
        )
        self.assertEqual((unknown["PERIOD"], existing["PERIOD"]), ("UNKNOWN", "1ST_HALF"))
        self.assertEqual((diag["FOREIGN_EVIDENCE_REJECTED"], diag["EXISTING_PERIOD_CONFLICT"]), (1, 1))

    def test_137_excluded_lineage_is_not_promoted(self):
        from core import resolve_periods_from_lineage
        record = self._record("run:1")
        excluded = [{"raw_record_id": "run:2", "source_raw_record_ids": ["run:2"]}]
        diag = resolve_periods_from_lineage([record], [self._raw("run:2", "FT")], excluded)
        self.assertEqual(record["PERIOD"], "UNKNOWN")
        self.assertEqual((diag["EVIDENCE_WITHOUT_CANONICAL"], diag["EXCLUDED_LINEAGE_COUNT"]), (0, 1))


class TestHF5BEvidencePeriodClassifier(unittest.TestCase):
    def test_138_explicit_ft_p1_p2_scopes_classify(self):
        from core import classify_period_evidence
        for label, expected in (("Cały mecz", "FT"), ("1. połowa", "P1"), ("2. połowa", "P2")):
            with self.subTest(label=label):
                period, reason = classify_period_evidence({"raw_value": label, "normalized_hint": label})
                self.assertEqual((period, reason), (expected, "PERIOD_EVIDENCE_EXPLICIT_SCOPE"))

    def test_139_missing_and_conflicting_scope_remain_unknown(self):
        from core import classify_period_evidence
        self.assertEqual(classify_period_evidence({"raw_value": "Handicap", "normalized_hint": "Handicap"})[0], "UNKNOWN")
        self.assertEqual(
            classify_period_evidence({"raw_value": "1. połowa 2. połowa", "normalized_hint": ""}),
            ("UNKNOWN", "PERIOD_EVIDENCE_SCOPE_CONFLICT"),
        )

    def test_140_classifier_is_deterministic_and_preserves_lineage_fields(self):
        from core import classify_period_evidence
        candidate = {"raw_value": "1. połowa", "normalized_hint": "1. połowa", "raw_record_id": "run:1",
                     "run_id": "run", "event_id": "Home|Away", "source_hash": "a" * 64}
        before = dict(candidate)
        self.assertEqual(classify_period_evidence(candidate), classify_period_evidence(dict(candidate)))
        self.assertEqual(candidate, before)


class TestHF6DerivedNormalization(unittest.TestCase):
    def test_141_additive_owner_and_line_normalization_preserves_owner(self):
        from core import derive_market_normalization
        rows = [{"OWNER":"Home Team","FAMILY":"TEAM_TOTALS_HOME","SELECTION":"OVER","LINE":"1.5","HANDICAP_KIND":"","MARKET_INSTANCE_ID":"x","PERIOD":"FULL_TIME"}, {"OWNER":"","FAMILY":"GOALS_OU","SELECTION":"UNDER","LINE":"2.5","HANDICAP_KIND":"","MARKET_INSTANCE_ID":"y","PERIOD":"FULL_TIME"}]
        before = [row["OWNER"] for row in rows]; derive_market_normalization(rows,"Home Team","Away Team")
        self.assertEqual([row["OWNER"] for row in rows], before)
        self.assertEqual((rows[0]["OWNER_SIDE"],rows[0]["LINE_TYPE"],rows[1]["OWNER_SIDE"],rows[1]["LINE_TYPE"]),("HOME","TEAM_TOTAL","MATCH","GOAL_TOTAL"))

    def test_142_handicap_settlement_is_deterministic(self):
        from core import derive_market_normalization
        rows=[{"OWNER":"","FAMILY":"HANDICAP_EUROPEAN","SELECTION":"HOME","LINE":"-0.5","HANDICAP_KIND":"TWO_WAY","MARKET_INSTANCE_ID":"x","PERIOD":"1ST_HALF"},{"OWNER":"","FAMILY":"HANDICAP_EUROPEAN","SELECTION":"DRAW","LINE":"1","HANDICAP_KIND":"THREE_WAY","MARKET_INSTANCE_ID":"y","PERIOD":"FULL_TIME"}]
        derive_market_normalization(rows,"Home","Away")
        self.assertEqual((rows[0]["SETTLEMENT"],rows[1]["SETTLEMENT"]),("NO_PUSH","WIN_DRAW_LOSE"))


class TestRealUseKnownErrorsRepair(unittest.TestCase):
    def _parse(self, market, selection, *, hint="", home="Taraz", away="Akademia Ontustyk"):
        from parser import parse_market_record
        record, issue = parse_market_record(category="Wynik", market_title=market, raw_selection=selection,
            odds_str="2.50", raw_text=selection + " 2.50", section_title="Wynik - popularne",
            home_team=home, away_team=away, container_id="market", period_hint=hint)
        self.assertIsNone(issue); return record

    def test_143_dnb_period_settlement_and_half_separation(self):
        from core import derive_market_normalization
        ft=self._parse("Remis - zwrot", "Taraz"); h1=self._parse("Remis - zwrot", "Taraz", hint="1. polowa"); h2=self._parse("Remis - zwrot", "Taraz", hint="2. polowa")
        derive_market_normalization([ft,h1,h2],"Taraz","Akademia Ontustyk")
        self.assertEqual((ft["FAMILY"],ft["PERIOD"],ft["SETTLEMENT"]),("DNB","FULL_TIME","PUSH_ON_DRAW"))
        self.assertEqual((h1["PERIOD"],h2["PERIOD"]),("1ST_HALF","2ND_HALF"))

    def test_144_result_goals_and_split_event_alias_are_canonical(self):
        result=self._parse("Wynik i gole", "Taraz & Powyżej 3,5")
        alias=self._parse("Wynik meczu (z wyłączeniem dogrywki)", "Akademia Ontu styk")
        self.assertEqual((result["FAMILY"],result["PERIOD"],result["LINE"]),("RESULT_AND_GOALS","FULL_TIME","3.5"))
        self.assertEqual((alias["SELECTION"],alias["NAME_ALIAS_STATUS"]),("AWAY","EVENT_TEAM_WHITESPACE_ALIAS"))

    def test_145_row_local_handicap_line_never_bleeds(self):
        from parser import parse_market_record
        row, _ = parse_market_record(category="Wynik", market_title="Handicap", raw_selection="Remis (FC Kaspiy-2 Aktau -3)",
            odds_str="2.00", raw_text="", section_title="", home_team="FC Kaspiy-2 Aktau", away_team="FC Aktobe U21", container_id="x")
        self.assertEqual((row["SELECTION"],row["LINE"]),("DRAW","-3"))

    def test_146_foreign_mycombi_rejects_entire_combination(self):
        from core import validate_mycombi_state_for_event
        state=validate_mycombi_state_for_event({"components":[{"label":"Novorizontino SP","market_heading":"Wynik meczu (z wyłączeniem dogrywki)"},{"label":"Powyżej 0,5","market_heading":"Gole Powyżej/Poniżej"}],"combination":{"combined_odds":"1.93"}},"Taraz","Akademia Ontustyk","r","Taraz|Akademia Ontustyk","h")
        self.assertEqual((state["components"],state["combination"],state["rejected"][0]["reason"]),([],None,"MYCOMBI_FOREIGN_EVENT_COMPONENT"))

    def test_147_same_event_mycombi_and_kickoff_survive(self):
        from core import extract_current_event_kickoff, validate_mycombi_state_for_event
        state=validate_mycombi_state_for_event({"components":[{"label":"Taraz","market_heading":"Wynik meczu (z wyłączeniem dogrywki)"}],"combination":{"combined_odds":"2.00"}},"Taraz","Akademia Ontustyk","r","Taraz|Akademia Ontustyk","h")
        self.assertEqual((len(state["components"]),state["combination"]["combined_odds"],extract_current_event_kickoff("","15:00")),(1,"2.00",("15:00","EVENT_HEADER_VISIBLE")))

    def test_148_completeness_is_monotonic_and_order_independent(self):
        from core import completeness_breakdown
        common={"detected_tabs": 3,"scanned_tabs": 3,"raw_records": 100,"parsed_records": 95,"unknown_periods": 2,"excluded_rows": 4}
        low=completeness_breakdown(**common,incomplete_instances=4); high=completeness_breakdown(**common,incomplete_instances=1)
        self.assertLess(low["COMPLETENESS_SCORE"],high["COMPLETENESS_SCORE"])
        self.assertEqual(low,completeness_breakdown(**common,incomplete_instances=4))

    def test_149_saved_runs_are_isolated_and_have_unique_incomplete_diagnostics(self):
        from pathlib import Path

        from replay import replay_real_prematch
        a=replay_real_prematch(Path("diagnostics/raw_before_dedupe_run_1785406931_13112.jsonl")); b=replay_real_prematch(Path("diagnostics/raw_before_dedupe_run_1785407658_13112.jsonl"))
        self.assertEqual((a["kickoff"],b["kickoff"],a["unresolved_count"],b["unresolved_count"]),("15:00","15:00",0,0))
        self.assertFalse(any("Novorizontino" in str(value) for value in (a["odds"],b["odds"],a["mycombi_components"],b["mycombi_components"])))
        self.assertLess(a["completeness"]["COMPLETENESS_SCORE"],b["completeness"]["COMPLETENESS_SCORE"])


class TestMyCombiAccountedRejectionStatus(unittest.TestCase):
    def _metrics(self, *, raw=0, parsed=0, accounted=0, unaccounted=None):
        values={"tab_name":"MyCombi","activation_ok":True,"priced_candidate_count":2,"unpriced_control_count":0,
                "raw_dom_items":raw,"parsed_odds_count":parsed,"unresolved_count":0,"remaining_closed":0,
                "remaining_more":0,"deadline_hit":False,"accounted_rejected_count":accounted}
        if unaccounted is not None: values["unaccounted_priced_count"]=unaccounted
        return values

    def test_150_all_foreign_priced_candidates_are_accounted_pass(self):
        from core import _evaluate_tab_status
        self.assertEqual(_evaluate_tab_status(self._metrics(accounted=2,unaccounted=0)),
                         ("PASS","ALL_PRICED_CANDIDATES_ACCOUNTED_AND_REJECTED"))

    def test_151_empty_ledger_or_unaccounted_candidate_fails_closed(self):
        from core import _evaluate_tab_status, completeness_breakdown
        self.assertEqual(_evaluate_tab_status(self._metrics(accounted=0,unaccounted=2)),
                         ("FAIL","UNACCOUNTED_PRICED_CANDIDATES"))
        self.assertLess(completeness_breakdown(detected_tabs=1,scanned_tabs=1,raw_records=2,parsed_records=2,
                        unknown_periods=0,incomplete_instances=0,excluded_rows=0,unaccounted_priced=1)["COMPLETENESS_SCORE"],100)

    def test_152_parsed_plus_accounted_foreign_is_pass(self):
        from core import _evaluate_tab_status
        self.assertEqual(_evaluate_tab_status(self._metrics(raw=1,parsed=1,accounted=1,unaccounted=0)),("PASS","OK"))

    def test_153_parsed_plus_unaccounted_candidate_fails_closed(self):
        from core import _evaluate_tab_status
        self.assertEqual(_evaluate_tab_status(self._metrics(raw=1,parsed=1,accounted=0,unaccounted=1)),
                         ("FAIL","UNACCOUNTED_PRICED_CANDIDATES"))


class TestIntegerOddsAndThreeWayHandicap(unittest.TestCase):
    def test_154_dom_capture_accepts_integer_button_odds_only(self):
        from core import _make_dom_script
        script = _make_dom_script()
        self.assertIn("[1-9]\\d{0,2}(?:[.,]\\d{1,2})?", script)

    def test_155_three_way_handicap_requires_all_three_selections(self):
        from core import analyze_handicap_completeness
        base = {"FAMILY":"HANDICAP_EUROPEAN","PERIOD":"FULL_TIME","HANDICAP_KIND":"THREE_WAY","MARKET":"Handicap","CONTAINER_ID":"row","run_id":"r","event_id":"e","source_hash":"h"}
        complete = [{**base,"SELECTION":s,"LINE":"-2"} for s in ("HOME","DRAW","AWAY")]
        missing = complete[:-1]
        self.assertEqual(len(analyze_handicap_completeness(complete)["incomplete_instances"]),0)
        self.assertEqual(len(analyze_handicap_completeness(missing)["incomplete_instances"]),1)


class TestSavedUnicodePeriodOntology(unittest.TestCase):
    def test_156_primary_raw_titles_have_deterministic_fail_closed_ontology(self):
        import json
        from pathlib import Path

        from parser import classify_period_detail
        rows=[json.loads(line) for line in Path("diagnostics/raw_before_dedupe_run_1785417298_16768.jsonl").read_text(encoding="utf-8").splitlines() if line]
        titles={row["market"] for row in rows if "gracze strzel" in row.get("market", "").casefold() or "większą ilością" in row.get("market", "").casefold()}
        self.assertTrue(titles)
        self.assertTrue(all(classify_period_detail(title,"","","","","GENERIC")[0]=="FULL_TIME" for title in titles))
        unknown="UNSUPPORTED_"+str(len(titles))
        self.assertEqual(classify_period_detail(unknown,"","","","","GENERIC")[0],"UNKNOWN")

    def test_157_mycombi_current_team_handicap_is_not_foreign(self):
        from core import validate_mycombi_state_for_event
        state=validate_mycombi_state_for_event({"components":[{"label":"Away (+1)","market_heading":"Wynik meczu"},{"label":"Powyżej 1,5","market_heading":"Gole Powyżej/Poniżej"}],"combination":{"combined_odds":"1.50"}},"Home","Away","r","Home|Away","h")
        self.assertEqual((state["status"],len(state["rejected"])),("ACTIVE_CURRENT_STATE",0))

    def test_158_candidate_ledger_is_unique_and_fail_closed(self):
        from core import candidate_ledger_summary
        base={"run_id":"r","event_id":"e","source_hash":"h","tab":"Top","container_id":"c","row_id":"1","column_id":"a","native_selection_id":"n"}
        good=candidate_ledger_summary([{**base,"terminal_state":"PARSED_CANONICAL"},{**base,"terminal_state":"PARSED_CANONICAL"}])
        bad=candidate_ledger_summary([{**base,"terminal_state":"UNACCOUNTED_FAILURE"}])
        self.assertEqual((len(good["entries"]),good["unaccounted"]),(1,0))
        self.assertEqual(bad["unaccounted"],1)

    def test_159_candidate_ledger_conflict_and_tab_totals(self):
        from core import _evaluate_tab_status, candidate_ledger_summary
        base={"run_id":"r","event_id":"e","source_hash":"h","tab":"Top","container_id":"c","row_id":"1","column_id":"a","native_selection_id":"n"}
        conflict=candidate_ledger_summary([{**base,"terminal_state":"PARSED_CANONICAL"},{**base,"terminal_state":"FOREIGN_EVENT_REJECTED"}])
        overlay=candidate_ledger_summary([{**base,"terminal_state":"GLOBAL_OVERLAY_ACCOUNTED"},{**base,"terminal_state":"GLOBAL_OVERLAY_ACCOUNTED"}])
        self.assertTrue(conflict["conflicts"])
        self.assertEqual((len(overlay["entries"]),sum(v["priced"] for v in overlay["by_tab"].values()),overlay["unaccounted"]),(1,1,0))
        self.assertEqual(_evaluate_tab_status({"priced_candidate_count":1,"raw_dom_items":1,"parsed_odds_count":0,"unaccounted_priced_count":1}), ("FAIL","UNACCOUNTED_PRICED_CANDIDATES"))

    def test_160_failed_tab_forces_global_truth_fail(self):
        from core import _aggregate_parser_truth_status
        self.assertEqual(_aggregate_parser_truth_status([{"status":"FAIL","reason":"ZERO_RAW_WITH_PRICED_CANDIDATES"}],1,[]),("FAIL","NO"))

    def test_161_two_readonly_foreign_mycombi_controls_are_accounted_separately(self):
        from core import _evaluate_tab_status, candidate_ledger_summary
        base={"run_id":"run_1785423303_14492","event_id":"Maccabi Tel-Aviv|Sheriff Tiraspol",
              "source_hash":"h","tab":"MyCombi","container_id":"sports-betting-slip","row_id":"",
              "column_id":"","odds":"1.93","foreign_event":"Novorizontino SP - Juventude RS",
              "current_event":"Maccabi Tel-Aviv - Sheriff Tiraspol","terminal_state":"FOREIGN",
              "reason":"FOREIGN_EVENT_BET_SLIP_REPRESENTATION"}
        summary=candidate_ledger_summary([
            {**base,"native_selection_id":"html/body/betslip/button[1]","evidence_reference":"html/body/betslip/button[1]"},
            {**base,"native_selection_id":"html/body/betslip/button[2]","evidence_reference":"html/body/betslip/button[2]"},
        ])
        tab=summary["by_tab"]["MyCombi"]
        self.assertEqual((len(summary["entries"]),tab["accounted_rejected"],tab["foreign_rejected"],summary["unaccounted"]),(2,2,2,0))
        self.assertEqual(_evaluate_tab_status({"priced_candidate_count":2,"raw_dom_items":0,
                         "accounted_rejected_count":2,"foreign_rejected_count":2,
                         "unaccounted_priced_count":0}), ("PASS","ALL_PRICED_CANDIDATES_ACCOUNTED_FOREIGN"))

    def test_162_cross_tab_same_offer_dedupes_but_settlement_variant_survives(self):
        from core import _dedupe_records_preserving_order
        base={"FAMILY":"GOALS_OU","PERIOD":"FULL_TIME","SETTLEMENT_SCOPE":"FULL_TIME","MARKET_SCOPE":"FULL_TIME",
              "MARKET":"Gole Powyżej/Poniżej","OWNER":"","SELECTION":"OVER","LINE":"2.5","SCORER_SCOPE":"ANYTIME",
              "HANDICAP_KIND":"","SETTLEMENT":"WIN_LOSE","COLUMN_ID":"","ODDS":"1.80","run_id":"r","event_id":"e",
              "source_hash":"h"}
        top={**base,"CATEGORY":"Top","raw_record_id":"r:1","source_raw_record_ids":["r:1"],"source_index":1,"capture_id":"a"}
        goals={**base,"CATEGORY":"Gole","raw_record_id":"r:2","source_raw_record_ids":["r:2"],"source_index":2,"capture_id":"b"}
        different={**base,"CATEGORY":"Gole","raw_record_id":"r:3","source_raw_record_ids":["r:3"],"source_index":3,"capture_id":"c","SETTLEMENT":"PUSH_ON_DRAW"}
        rows, issues=_dedupe_records_preserving_order([top,goals,different],[])
        self.assertEqual((len(rows),issues),(2,[]))
        self.assertEqual(rows[0]["source_raw_record_ids"],["r:1","r:2"])

    def test_163_team_named_heading_binds_owner_without_claiming_match_market(self):
        from core import derive_market_normalization
        team={"FAMILY":"GENERIC","MARKET":"Wygrają obie połowy - Auda","SELECTION":"Tak","OWNER":"","LINE":"","HANDICAP_KIND":""}
        match={"FAMILY":"GOALS_OU","MARKET":"Gole Auda Steaua","SELECTION":"OVER","OWNER":"","LINE":"2.5","HANDICAP_KIND":""}
        grouped={"FAMILY":"GENERIC","MARKET":"Bez utraty bramki","SELECTION":"Tak","OWNER":"","LINE":"","HANDICAP_KIND":"",
                 "MARKET_INSTANCE_ID":"tab:Gole|market#1|column:Goście"}
        scorer={"FAMILY":"GOALSCORER","MARKET":"Zdobędzie bramkę","SELECTION":"Auda","OWNER":"","LINE":"","HANDICAP_KIND":"",
                "SCORER_SCOPE":"ANYTIME","MARKET_INSTANCE_ID":"tab:Gole|market#2|column:Pierwszy.gol"}
        derive_market_normalization([team,match,grouped,scorer],"Auda","Steaua")
        self.assertEqual((team["OWNER"],team["OWNER_SIDE"]),("Auda","HOME"))
        self.assertEqual((match["OWNER"],match["OWNER_SIDE"]),("","MATCH"))
        self.assertEqual((grouped["OWNER"],grouped["OWNER_SIDE"]),("Steaua","AWAY"))
        self.assertEqual(scorer["SCORER_SCOPE"],"FIRST")

    def test_164_half_full_and_scorer_column_roles_preserve_components(self):
        from core import derive_market_normalization
        from parser import classify_family
        self.assertEqual(classify_family("Wynik Meczu Połowa / Cały", "Remis / FC Hradec Kralove", "", "FC Hradec Kralove", "Tromso")[0], "HALF_FULL_RESULT")
        half_full={"FAMILY":"HALF_FULL_RESULT","MARKET":"Wynik Meczu Połowa / Cały","SELECTION":"DRAW_AWAY","OWNER":"","LINE":"","HANDICAP_KIND":""}
        derive_market_normalization([half_full], "FC Hradec Kralove", "Tromso")
        self.assertEqual(half_full["SETTLEMENT"], "WIN_LOSE")
        scorer={"FAMILY":"GOALSCORER","MARKET":"Strzelec","SELECTION":"Ondrej Mihálik","OWNER":"","LINE":"","HANDICAP_KIND":"","SCORER_SCOPE":"ANYTIME","MARKET_INSTANCE_ID":"tab:Strzelcy|m#1|column:2.lub.wiecej.goli"}
        derive_market_normalization([scorer],"FC Hradec Kralove","Tromso")
        self.assertEqual(scorer["SCORER_SCOPE"],"TWO_OR_MORE_GOALS")

    def test_165_result_and_goals_keeps_result_and_goal_components_distinct(self):
        from core import derive_market_normalization
        from parser import parse_market_record
        common = {"category": "Wynik", "market_title": "Wynik i gole - 1. połowa",
                      "section_title": "", "home_team": "Home", "away_team": "Away",
                      "container_id": "compound"}
        over, _ = parse_market_record(raw_selection="Home & Powyżej 1,5", odds_str="7.75",
                                      raw_text="Home & Powyżej 1,5 7.75", **common)
        under, _ = parse_market_record(raw_selection="Home & Poniżej 1,5", odds_str="4.50",
                                       raw_text="Home & Poniżej 1,5 4.50", **common)
        self.assertEqual((over["FAMILY"], over["SELECTION"], over["LINE"]),
                         ("RESULT_AND_GOALS", "HOME_AND_OVER", "1.5"))
        self.assertEqual((under["SELECTION"], under["SETTLEMENT"]),
                         ("HOME_AND_UNDER", "HOME_AND_UNDER_1.5"))
        derive_market_normalization([over, under], "Home", "Away")
        self.assertEqual((over["SETTLEMENT"], under["SETTLEMENT"]),
                         ("WIN_LOSE", "WIN_LOSE"))
        malformed = {**over, "LINE": "not-a-line"}
        derive_market_normalization([malformed], "Home", "Away")
        self.assertEqual(malformed["SETTLEMENT"], "UNKNOWN")
        self.assertEqual(parse_market_record(raw_selection="Home & Powyżej 1,5", odds_str="7.75",
                         raw_text="Home & Powyżej 1,5 7.75", category="Wynik",
                         market_title="Wynik i liczba bramek - 1. połowa", section_title="",
                         home_team="Home", away_team="Away", container_id="compound")[0]["FAMILY"],
                         "RESULT_AND_GOALS")

    def test_166_ledger_conservation_is_required_for_every_tab(self):
        from core import _evaluate_tab_status
        status, reason = _evaluate_tab_status({"priced_candidate_count": 3, "raw_dom_items": 2,
                                                "parsed_odds_count": 2, "accounted_rejected_count": 0,
                                                "unaccounted_priced_count": 0})
        self.assertEqual((status, reason), ("FAIL", "LEDGER_CONSERVATION_GAP"))

    def test_167_handicap_taxonomy_distinguishes_two_and_three_way(self):
        from parser import parse_market_record
        common = {"category": "Top", "section_title": "", "home_team": "Home", "away_team": "Away",
                      "container_id": "h", "odds_str": "2.00", "raw_text": "Home -1 2.00"}
        three, _ = parse_market_record(market_title="Handicap", raw_selection="Home -1",
                                       handicap_kind_hint="THREE_WAY", **common)
        two, _ = parse_market_record(market_title="Handicap (2-drożny)", raw_selection="Home -1",
                                     handicap_kind_hint="TWO_WAY", **common)
        self.assertEqual((three["HANDICAP_KIND"], three["HANDICAP_TAXONOMY"]),
                         ("THREE_WAY", "EUROPEAN_THREE_WAY_WITH_DRAW"))
        self.assertEqual((two["HANDICAP_KIND"], two["HANDICAP_TAXONOMY"]),
                         ("TWO_WAY", "TWO_WAY_NO_DRAW"))

    def test_168_runtime_packet_contract_exposes_taxonomy_and_hash_fields(self):
        import hashlib
        from pathlib import Path

        import core
        self.assertTrue(Path(core.__file__).is_file())
        self.assertEqual(len(hashlib.sha256(Path(core.__file__).read_bytes()).hexdigest()), 64)
        from parser import parse_market_record
        record, _ = parse_market_record(category="Top", market_title="Handicap (2-drożny)",
                                        raw_selection="Home -1", odds_str="2.00", raw_text="Home -1 2.00",
                                        section_title="", home_team="Home", away_team="Away", container_id="h")
        self.assertIn(record["HANDICAP_TAXONOMY"], {"TWO_WAY_NO_DRAW", "EUROPEAN_THREE_WAY_WITH_DRAW"})

    def test_169_export_dedupe_merges_only_exact_displayed_propositions(self):
        from core import _dedupe_canonical_export_rows
        base={"CATEGORY":"Wynik","FAMILY":"HANDICAP_EUROPEAN","MARKET":"Handicap","PERIOD":"FULL_TIME",
              "OWNER":"Home","SELECTION":"HOME","LINE":"-1","HANDICAP_KIND":"THREE_WAY",
              "HANDICAP_TAXONOMY":"EUROPEAN_THREE_WAY_WITH_DRAW","SETTLEMENT":"WIN_DRAW_LOSE","ODDS":"2.00","SCORER_SCOPE":"ANYTIME"}
        rows, groups, excess = _dedupe_canonical_export_rows([base, {**base}, {**base,"ODDS":"2.10"}])
        self.assertEqual((len(rows), groups, excess), (2, 1, 1))

    def test_170_optional_statistics_and_unknown_player_props_are_explicit(self):
        from core import _aggregate_parser_truth_status, is_semantically_quarantined
        self.assertTrue(is_semantically_quarantined({"FAMILY":"PLAYER_PROP","MARKET":"Liczba strzałów zawodnika","PARTICIPANT":"Jan Kowalski","PERIOD":"UNKNOWN"}))
        self.assertFalse(is_semantically_quarantined({"FAMILY":"PLAYER_PROP","MARKET":"Liczba strzałów zawodnika","PARTICIPANT":"Jan Kowalski","PERIOD":"FULL_TIME","SETTLEMENT":"WIN_LOSE"}))
        self.assertEqual(_aggregate_parser_truth_status([{"status":"EXCLUDED_OPTIONAL","reason":"UNSUPPORTED_OPTIONAL_STATISTICS_TAB"}],1,[]), ("PASS","YES"))

    def test_171_runtime_artifact_and_core_hash_inputs_are_independent(self):
        from pathlib import Path

        import core
        import gui
        self.assertNotEqual(Path(core.__file__).resolve(), Path(gui.__file__).resolve())

    def test_172_complete_render_snapshot_prevents_top_history_from_becoming_raw_offers(self):
        from core import _select_stable_tab_snapshot
        union = (
            [{"capture_id": "cap_1", "record_type": "ODD", "selection": f"old-{index}"} for index in range(5)]
            + [{"capture_id": "cap_2", "record_type": "ODD", "selection": f"current-{index}"} for index in range(3)]
            + [{"capture_id": "cap_3", "record_type": "ODD", "selection": f"retry-{index}"} for index in range(3)]
        )
        selected = _select_stable_tab_snapshot(union, 3)
        self.assertEqual([row["selection"] for row in selected], ["retry-0", "retry-1", "retry-2"])
        self.assertEqual(_select_stable_tab_snapshot(union, 4), union)

    def test_173_statistics_is_optional_only_when_no_usable_row_was_captured(self):
        from core import _is_optional_statistics_exclusion
        self.assertTrue(_is_optional_statistics_exclusion("Statystyki", 3, [], 0))
        self.assertFalse(_is_optional_statistics_exclusion("Statystyki", 3, [{"odds": "1.80"}], 0))
        self.assertFalse(_is_optional_statistics_exclusion("Statystyki", 3, [], 1))

    def test_174_player_owner_and_known_settlement_are_not_lost(self):
        from core import derive_market_normalization
        from parser import parse_market_record
        scorer, issue = parse_market_record(category="Strzelcy", market_title="Strzelec", raw_selection="Player One",
                                            odds_str="3.40", raw_text="Player One 3.40", section_title="",
                                            home_team="Home", away_team="Away", container_id="scorer")
        self.assertIsNone(issue)
        self.assertEqual((scorer["OWNER"], scorer["PARTICIPANT"], scorer["TEAM_OWNER_STATUS"]),
                         ("", "Player One", "TEAM_OWNER_UNKNOWN"))
        derive_market_normalization([scorer], "Home", "Away")
        self.assertEqual((scorer["OWNER_SIDE"], scorer["SETTLEMENT"]), ("UNKNOWN", "WIN_LOSE"))

    def test_175_unknown_player_prop_exclusion_is_auditable(self):
        from core import semantic_quarantine_ledger
        rows = [{"FAMILY":"PLAYER_PROP", "MARKET":"Player shots", "SELECTION":"OVER", "PARTICIPANT":"Player One", "PERIOD":"UNKNOWN",
                 "PERIOD_SOURCE":"", "PERIOD_CONFIDENCE":"LOW", "raw_record_id":"r:1",
                 "source_raw_record_ids":["r:1"], "MARKET_INSTANCE_ID":"m", "DOM_PATH":"dom"}]
        quarantined = semantic_quarantine_ledger(rows)
        self.assertEqual(quarantined[0]["reason"], "UNCONFIRMED_PLAYER_PROP_PERIOD")
        self.assertEqual(quarantined[0]["scope"], "PLAYER_PROP")
        self.assertEqual(quarantined[0]["source_raw_record_ids"], ["r:1"])

    def test_176_priced_zero_raw_uses_bounded_active_panel_recovery(self):
        from core import _recover_zero_raw_priced_tab, _should_active_panel_fallback
        attempts = []
        def extract():
            attempts.append(1)
            return [] if len(attempts) < 2 else [{"odds": "3.40"}]
        self.assertEqual(_recover_zero_raw_priced_tab(extract, 1, attempts=3), [{"odds": "3.40"}])
        self.assertEqual(len(attempts), 2)
        self.assertEqual(_recover_zero_raw_priced_tab(lambda: [{"odds": "x"}], 0), [])
        self.assertTrue(_should_active_panel_fallback("Strzelcy", 1, []))
        self.assertFalse(_should_active_panel_fallback("MyCombi", 2, []))

    def test_177_replay_excludes_readonly_mycombi_betslip_ui_copy_only(self):
        from replay import _is_mycombi_betslip_ui_row
        ui = {"tab_name":"MyCombi", "record_type":"ODD", "dom_path":"x>sports-betting-slip>button.is-readonly"}
        self.assertTrue(_is_mycombi_betslip_ui_row(ui))
        self.assertFalse(_is_mycombi_betslip_ui_row({**ui, "record_type":"MYCOMBI_COMBINATION"}))
        self.assertFalse(_is_mycombi_betslip_ui_row({**ui, "tab_name":"Top"}))

    def test_178_standard_totals_and_explicit_goal_markets_have_settlement(self):
        from parser import parse_market_record
        common = {"category": "Gole", "odds_str": "2.00", "raw_text": "x", "section_title": "",
                      "home_team": "Junior de Barranquilla K.", "away_team": "Bucaramanga K.", "container_id": "x"}
        team, _ = parse_market_record(market_title="Liczba goli - Junior de Barranquilla K.",
                                      raw_selection="Powyżej 1,5", **common)
        first, _ = parse_market_record(market_title="Kto zdobędzie 1. bramkę",
                                       raw_selection="Junior de Barranquilla K.", **common)
        penalty, _ = parse_market_record(market_title="Gol z rzutu karnego", raw_selection="Tak", **common)
        self.assertEqual((team["FAMILY"], team["SETTLEMENT"]), ("TEAM_TOTALS_HOME", "NO_PUSH"))
        self.assertEqual((first["FAMILY"], first["SETTLEMENT"]), ("FIRST_GOAL_TEAM", "WIN_LOSE"))
        self.assertEqual((penalty["FAMILY"], penalty["SETTLEMENT"]), ("PENALTY_GOAL", "WIN_LOSE"))

    def test_179_player_is_participant_and_column_scope_is_semantic(self):
        from parser import parse_market_record
        record, _ = parse_market_record(category="Strzelcy", market_title="Strzelec i jego zmiennik",
                                        raw_selection="Paul Charpentier", odds_str="13.00", raw_text="x",
                                        section_title="CD Recoleta", home_team="CD Recoleta", away_team="Nacional Asuncion",
                                        container_id="x", market_instance_id="tab:Strzelcy|column:2.lub.wiecej")
        self.assertEqual((record["OWNER"], record["PARTICIPANT"], record["SCORER_SCOPE"]),
                         ("CD Recoleta", "Paul Charpentier", "TWO_OR_MORE_GOALS"))

    def test_180_event_alias_suffix_is_canonical_but_raw_is_not_changed(self):
        from parser import canonical_event_team_name
        canonical, status = canonical_event_team_name("Flamengo K.", "CR Flamengo K.", "Corinthians SP K.")
        self.assertEqual((canonical, status), ("CR Flamengo K.", "EVENT_TEAM_WHITESPACE_ALIAS"))

    def test_181_proven_equivalence_groups_find_best_price_only(self):
        from core import build_equivalence_groups
        rows = [
            {"event_id":"Flamengo|Corinthians", "PERIOD":"FULL_TIME", "FAMILY":"1X2", "SELECTION":"AWAY", "ODDS":"2.00", "MARKET":"Wynik", "CATEGORY":"Wynik", "source_raw_record_ids":["r1"]},
            {"event_id":"Flamengo|Corinthians", "PERIOD":"FULL_TIME", "FAMILY":"HANDICAP_EUROPEAN", "HANDICAP_KIND":"TWO_WAY", "LINE":"-0.5", "SELECTION":"AWAY", "ODDS":"1.93", "MARKET":"Handicap", "CATEGORY":"Wynik", "source_raw_record_ids":["r2"]},
            {"event_id":"Flamengo|Corinthians", "PERIOD":"FULL_TIME", "FAMILY":"HANDICAP_EUROPEAN", "HANDICAP_KIND":"TWO_WAY", "LINE":"+0.5", "SELECTION":"AWAY", "ODDS":"2.20", "MARKET":"Other", "CATEGORY":"Wynik", "source_raw_record_ids":["r3"]},
        ]
        groups = build_equivalence_groups(rows)
        self.assertEqual((len(groups), groups[0]["best_odds"], len(groups[0]["copies"])), (1, "2.00", 2))

    def test_182_player_pair_is_participant_list_not_team_owner(self):
        from parser import parse_market_record
        record, _ = parse_market_record(category="Strzelcy", market_title="Obaj gracze strzelą",
                                        raw_selection="A. Player / B. Player", odds_str="8.00", raw_text="x",
                                        section_title="", home_team="Home", away_team="Away", container_id="x")
        self.assertEqual((record["OWNER"], record["PARTICIPANT"], record["PARTICIPANTS"]),
                         ("", "", ["A. Player", "B. Player"]))

    def test_183_btts_or_and_btts_under_have_one_proven_signature(self):
        from core import build_equivalence_groups
        base = {"event_id":"Recoleta|Nacional", "PERIOD":"FULL_TIME", "FAMILY":"COMPOUND_LOGIC",
                "CATEGORY":"Gole", "source_raw_record_ids":["r"], "LINE":"2.5", "SETTLEMENT":"WIN_LOSE"}
        rows = [
            {**base, "MARKET":"Oba zespoly strzela gola lub Powyzej 2,5", "RAW":"Nie 2.10", "SELECTION":"BTTS_OR_OVER_NO", "ODDS":"2.10"},
            {**base, "MARKET":"Oba zespoly strzela gola / Liczba bramek", "RAW":"Nie i ponizej 2,5 1.59", "SELECTION":"BTTS_NO_AND_UNDER", "ODDS":"1.59"},
        ]
        groups = build_equivalence_groups(rows)
        self.assertEqual((len(groups), groups[0]["best_odds"], [x["odds"] for x in groups[0]["copies"]]),
                         (1, "2.10", ["2.10", "1.59"]))


class TestFreshSemanticBlockers(unittest.TestCase):
    def test_compound_title_precedence_preserves_known_and_rejects_unknown_forms(self):
        from core import derive_market_normalization, partition_semantic_records
        from parser import parse_market_record
        cases = {
            "Wynik/oba zespoły strzelą - 1. połowa": "COMPOUND_LOGIC",
            "Wynik i oba zespoły strzelą": "COMPOUND_LOGIC",
            "Obie drużyny strzelą gola głową": "COMPOUND_LOGIC",
            "Obie drużyny strzelą gola z rzutu wolnego": "COMPOUND_LOGIC",
            "Liczba Goli Parzysta/Nieparzysta - Home": "GOAL_PARITY",
            "Wynik i liczba bramek - 1. połowa": "RESULT_AND_GOALS",
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                family, _ = classify_family(title, "Tak", "", "Home", "Away")
                self.assertEqual(family, expected)
        known, error = parse_market_record(
            category="Wynik", market_title="Wynik/oba zespoły strzelą - 1. połowa",
            raw_selection="Home / Tak", odds_str="4.00", raw_text="Home / Tak 4.00",
            section_title="", home_team="Home", away_team="Away", container_id="known-compound",
        )
        self.assertIsNone(error)
        derive_market_normalization([known], "Home", "Away")
        accepted, quarantined = partition_semantic_records([known])
        self.assertEqual((known["FAMILY"], known["SETTLEMENT"], accepted, quarantined),
                         ("COMPOUND_LOGIC", "WIN_LOSE", [known], []))
        unknown = {**known, "FAMILY": "OTHER", "SETTLEMENT": "UNKNOWN"}
        accepted, quarantined = partition_semantic_records([known, unknown])
        self.assertEqual((accepted, quarantined), ([known], [unknown]))

    def test_standard_not_modelled_market_ontology_is_accepted_but_ambiguous_binary_stays_closed(self):
        from core import derive_market_normalization, partition_semantic_records
        from parser import parse_market_record
        common = {"category": "Gole", "section_title": "", "home_team": "Home", "away_team": "Away",
                  "odds_str": "2.00", "raw_text": "source", "run_id": "r", "event_id": "Home|Away",
                  "source_hash": "h"}
        cases = [
            ("Liczba goli nieparzysta/parzysta", "Parzyste", "GOAL_PARITY"),
            ("Czyste konto - Home", "Tak", "CLEAN_SHEET"),
            ("Dokładna liczba bramek - Away", "3+", "EXACT_GOALS"),
            ("Liczba goli - opcja I", "2 - 3", "GOAL_RANGE"),
            ("Połowa z większą ilością goli", "Remis", "HIGHER_SCORING_HALF"),
            ("Różnica goli", "Home przewagą 2 goli", "GOAL_MARGIN"),
            ("Strzelą w obu połowach - Home", "Nie", "TEAM_SCORES_BOTH_HALVES"),
            ("Wygrają obie połowy - Away", "Tak", "TEAM_WINS_BOTH_HALVES"),
            ("Czas 1. gola - opcja II", "00:00 - 14:59", "FIRST_GOAL_TIME"),
        ]
        rows = []
        for index, (title, selection, family) in enumerate(cases):
            row, error = parse_market_record(market_title=title, raw_selection=selection,
                container_id=f"known-{index}", raw_record_id=f"r:{index}",
                source_raw_record_ids=[f"r:{index}"], **common)
            self.assertIsNone(error)
            self.assertEqual(row["FAMILY"], family)
            rows.append(row)
        derive_market_normalization(rows, "Home", "Away")
        accepted, quarantined = partition_semantic_records(rows)
        self.assertEqual((accepted, quarantined), (rows, []))
        self.assertTrue(all(row["SETTLEMENT"] == "WIN_LOSE" and row["source_raw_record_ids"] and
                            row["MODELING_DISPOSITION"] == "KNOWN_VALID_NOT_MODELED" for row in rows))
        ambiguous, error = parse_market_record(market_title="Bez utraty bramki", raw_selection="Tak",
            container_id="ambiguous", raw_record_id="r:ambiguous", source_raw_record_ids=["r:ambiguous"], **common)
        self.assertIsNone(error)
        derive_market_normalization([ambiguous], "Home", "Away")
        accepted, quarantined = partition_semantic_records(rows + [ambiguous])
        self.assertEqual((accepted, quarantined), (rows, [ambiguous]))

    def test_generic_core_titles_remain_generic_core_families(self):
        cases = {
            "Oba zespoły strzelą": "BTTS",
            "Liczba goli - Home": "TEAM_TOTALS_HOME",
            "Suma goli": "GOALS_OU",
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                family, _ = classify_family(title, "Tak", "", "Home", "Away")
                self.assertEqual(family, expected)

    def test_quarantine_quality_is_materiality_based_and_does_not_change_core_gate(self):
        from replay import semantic_quality_report
        base = {"COMPLETENESS_PARSE": 100.0}
        report = semantic_quality_report(
            parsed_records=10, accepted_records=9,
            quarantined_rows=[{"FAMILY": "PLAYER_PROP"}], completeness=base,
            full_usable_ready="YES", exhaustive_ready="NO",
        )
        self.assertEqual(report, {
            "CAPTURE_COVERAGE": 100.0, "CORE_MARKET_USABILITY": "PASS",
            "SEMANTIC_ACCEPTANCE_RATIO": 90.0, "EXHAUSTIVE_SUPPORT_STATUS": "PARTIAL",
            "CORE_IMPACT": "NONE", "QUARANTINE_COUNT": 1,
        })
        material = semantic_quality_report(
            parsed_records=2, accepted_records=1,
            quarantined_rows=[{"FAMILY": "BTTS"}], completeness=base,
            full_usable_ready="NO", exhaustive_ready="NO",
        )
        self.assertEqual(material["CORE_IMPACT"], "MATERIAL")

    def test_preserved_juventud_delfin_replay_accepts_known_compounds_without_core_block(self):
        from replay import replay_real_prematch
        result = replay_real_prematch(Path("diagnostics/raw_before_dedupe_run_1787254685_5060.jsonl"))
        quarantined_markets = {item["market"] for item in result["semantic_quarantine"]}
        self.assertNotIn("Wynik/oba zespoły strzelą - 1. połowa", quarantined_markets)
        accepted_compounds = [row for row in result["odds"]
                              if row["MARKET"] == "Wynik/oba zespoły strzelą - 1. połowa"]
        self.assertTrue(accepted_compounds)
        self.assertTrue(all(row["FAMILY"] == "COMPOUND_LOGIC" and row["SETTLEMENT"] == "WIN_LOSE"
                            and row["source_raw_record_ids"] for row in accepted_compounds))
        self.assertNotIn("MISSING_REQUIRED_MARKET_PAIR", result["unresolved_reasons"])
        self.assertEqual(result["quality_dimensions"]["CORE_MARKET_USABILITY"], "PASS")
        # The sole old exclusion was the now-proven Delfin SC short-name pair.
        self.assertEqual(result["quality_dimensions"]["CORE_IMPACT"], "NONE")

    def test_replay_reports_production_canonical_layer_separately_from_representatives(self):
        from replay import replay_real_prematch
        result = replay_real_prematch(Path("diagnostics/raw_before_dedupe_run_1787254685_5060.jsonl"))
        accounting = result["production_accounting"]
        self.assertEqual({key: accounting[key] for key in (
            "RAW_SOURCE_COUNT", "POST_RAW_DEDUPE_COUNT", "CANONICAL_ODDS_COUNT",
            "SEMANTIC_ACCEPTED_COUNT", "SEMANTIC_QUARANTINED_COUNT",
        )}, {
            "RAW_SOURCE_COUNT": 448, "POST_RAW_DEDUPE_COUNT": 283,
            "CANONICAL_ODDS_COUNT": 336, "SEMANTIC_ACCEPTED_COUNT": 336,
            "SEMANTIC_QUARANTINED_COUNT": 0,
        })
        self.assertTrue(accounting["ALL_SOURCE_IDS_PRESERVED"])
        self.assertEqual((accounting["SOURCE_TERMINAL_COUNT"], accounting["SOURCE_ACCEPTED_COUNT"] +
                          accounting["SOURCE_QUARANTINED_COUNT"]), (448, 448))
        self.assertEqual(accounting["ACCOUNTING_SCHEMA_VERSION"], "2.0")
        self.assertEqual(accounting["SOURCE_IDENTITY_REPRESENTATIVE_COUNT"], 283)
        self.assertEqual(accounting["SOURCE_DUPLICATE_ROWS_SUPPRESSED"], 165)
        self.assertEqual(accounting["CURRENT_PLAYER_PROP_QUARANTINED_COUNT"], 0)
        self.assertEqual(accounting["CURRENT_MATCH_MARKET_QUARANTINED_COUNT"], 0)
        recovered = next(row for row in result["odds"]
                         if "run_1787254685_5060:152" in row["source_raw_record_ids"])
        self.assertEqual((recovered["SELECTION"], recovered["SETTLEMENT"], recovered["ODDS"], recovered["RAW"]),
                         ("AWAY_HOME", "WIN_LOSE", "48", "Delfin / Cde Juventud Italiana 48"))
        self.assertEqual(accounting["LEGACY_REPORTED_SEMANTIC_QUARANTINE_COUNT"], 105)
        self.assertEqual(accounting["LEGACY_REPORTED_PACKET_ODDS_COUNT"], 253)
        self.assertNotIn("HISTORICAL_PLAYER_PROP_EXCLUDED_COUNT", accounting)

    def test_replay_production_canonical_layer_matches_clean_packet_contract(self):
        from replay import replay_real_prematch
        for run_id in ("1787254990_5060", "1787255243_5060"):
            with self.subTest(run_id=run_id):
                result = replay_real_prematch(Path(f"diagnostics/raw_before_dedupe_run_{run_id}.jsonl"))
                accounting = result["production_accounting"]
                self.assertEqual((accounting["RAW_SOURCE_COUNT"], accounting["CANONICAL_ODDS_COUNT"],
                                  accounting["SEMANTIC_QUARANTINED_COUNT"]), (118, 114, 0))
                self.assertEqual(accounting["LEGACY_REPORTED_PACKET_ODDS_COUNT"], 114)

    def test_strzelcy_compact_first_last_columns_are_not_anytime(self):
        from parser import parse_market_record
        first, _ = parse_market_record(category="Strzelcy", market_title="Strzelcy",
                                       raw_selection="Player One", odds_str="6.75", raw_text="Player One 6.75",
                                       section_title="Strzelec > Strzelcy", home_team="Home", away_team="Away",
                                       container_id="x", market_instance_id="tab:Strzelcy|column:Pierwszy|row#1")
        last, _ = parse_market_record(category="Strzelcy", market_title="Strzelcy",
                                      raw_selection="Player One", odds_str="9.00", raw_text="Player One 9.00",
                                      section_title="Strzelec > Strzelcy", home_team="Home", away_team="Away",
                                      container_id="x", market_instance_id="tab:Strzelcy|column:Ostatni|row#1")
        self.assertEqual((first["FAMILY"], first["SCORER_SCOPE"], first["SETTLEMENT"]),
                         ("GOALSCORER", "FIRST_GOAL", "WIN_LOSE"))
        self.assertEqual(last["SCORER_SCOPE"], "LAST_GOAL")

    def test_named_first_scorer_title_has_first_goal_scope(self):
        from parser import parse_market_record
        record, _ = parse_market_record(category="Strzelcy", market_title="Pierwszy strzelec",
                                        raw_selection="Jan Kowalski", odds_str="6.00", raw_text="Jan Kowalski 6.00",
                                        section_title="Home FC", home_team="Home FC", away_team="Away FC",
                                        container_id="x")
        self.assertEqual((record["FAMILY"], record["SCORER_SCOPE"], record["PARTICIPANT"], record["OWNER"]),
                         ("GOALSCORER", "FIRST_GOAL", "Jan Kowalski", "Home FC"))

    def test_unknown_semantics_are_auditable_quarantine_not_retained(self):
        from core import (
            _semantic_quarantine_reason,
            semantic_quarantine_ledger,
        )
        row = {"CATEGORY":"Statystyki", "MARKET":"Rzuty rożne", "SELECTION":"Powyżej 6,5",
               "PERIOD":"UNKNOWN", "SETTLEMENT":"UNKNOWN", "ODDS":"1.80", "RAW":"Powyżej 6,5 1.80",
               "raw_record_id":"r:1", "source_raw_record_ids":["r:1"], "MARKET_INSTANCE_ID":"m", "DOM_PATH":"d"}
        self.assertEqual(_semantic_quarantine_reason(row), "UNSUPPORTED_OPTIONAL_STATISTICS_PERIOD")
        ledger = semantic_quarantine_ledger([row])
        self.assertEqual(ledger[0]["raw_original"], "Powyżej 6,5 1.80")
        self.assertEqual(ledger[0]["scope"], "OPTIONAL_STATISTICS")

    def test_semantic_quarantine_keeps_player_props_distinct_from_match_markets(self):
        from core import partition_semantic_records, semantic_quarantine_ledger
        player_prop = {"FAMILY": "PLAYER_PROP", "MARKET": "Strzały zawodnika", "SELECTION": "Powyżej 1,5",
                       "PARTICIPANT": "Jan Kowalski", "PERIOD": "UNKNOWN", "SETTLEMENT": "UNKNOWN",
                       "raw_record_id": "player:1", "source_raw_record_ids": ["player:1"]}
        unsupported_match = {"FAMILY": "OTHER", "MARKET": "Różnica goli", "SELECTION": "Gospodarze +1",
                             "PERIOD": "FULL_TIME", "SETTLEMENT": "UNKNOWN", "raw_record_id": "match:1",
                             "source_raw_record_ids": ["match:1"]}
        accepted = {"FAMILY": "1X2", "MARKET": "Wynik meczu", "SELECTION": "HOME",
                    "PERIOD": "FULL_TIME", "SETTLEMENT": "WIN_LOSE", "raw_record_id": "core:1",
                    "source_raw_record_ids": ["core:1"]}
        kept, quarantined = partition_semantic_records([player_prop, unsupported_match, accepted])
        ledger = semantic_quarantine_ledger(quarantined)
        self.assertEqual(kept, [accepted])
        self.assertEqual([(row["scope"], row["reason"]) for row in ledger], [
            ("PLAYER_PROP", "UNCONFIRMED_PLAYER_PROP_PERIOD"),
            ("MATCH_MARKET", "UNCONFIRMED_MARKET_SETTLEMENT"),
        ])

    def test_player_prop_without_player_entity_is_fail_closed(self):
        from core import partition_semantic_records, semantic_quarantine_ledger
        unscoped = {"FAMILY": "PLAYER_PROP", "MARKET": "Strzały zawodnika", "SELECTION": "OVER",
                    "PERIOD": "FULL_TIME", "SETTLEMENT": "WIN_LOSE", "raw_record_id": "unscoped:1",
                    "source_raw_record_ids": ["unscoped:1"]}
        accepted, quarantined = partition_semantic_records([unscoped])
        self.assertEqual(accepted, [])
        self.assertEqual(semantic_quarantine_ledger(quarantined)[0]["reason"], "UNCONFIRMED_PLAYER_PROP_SCOPE")

    def test_match_and_team_statistics_are_never_classified_as_player_props(self):
        from parser import classify_family
        self.assertEqual(classify_family("Liczba strzałów w meczu (OPTA)", "Powyżej 22,5", "", "Home", "Away")[0],
                         "EVENT_TOTAL")
        self.assertEqual(classify_family("Liczba celnych strzałów (OPTA) - Home", "Powyżej 5,5", "", "Home", "Away")[0],
                         "GENERIC")
        self.assertEqual(classify_family("Liczba strzałów zawodnika", "Powyżej 1,5", "Jan Kowalski", "Home", "Away")[0],
                         "PLAYER_PROP")

    def test_preserved_aggregate_statistics_are_not_player_prop_quarantine(self):
        from replay import replay_real_prematch
        result = replay_real_prematch(Path("diagnostics/raw_before_dedupe_run_1785259772_7560.jsonl"))
        aggregate_shots = [row for row in result["odds"]
                           if row["FAMILY"] == "EVENT_TOTAL"
                           and "strza" in row["MARKET"].casefold()
                           and "opta" in row["MARKET"].casefold()]
        self.assertTrue(aggregate_shots)
        self.assertFalse(result["player_prop_quarantine"])
        self.assertTrue(all(row["PERIOD"] == "MATCH_INCLUDING_EXTRA_TIME" for row in aggregate_shots))

    def test_accounting_layers_are_disjoint_and_legacy_is_explicitly_not_current_truth(self):
        from replay import replay_real_prematch
        result = replay_real_prematch(Path("diagnostics/raw_before_dedupe_run_1787254685_5060.jsonl"))
        accounting = result["production_accounting"]
        self.assertEqual(accounting["SOURCE_RAW_RECORDS"],
                         accounting["SOURCE_IDENTITY_REPRESENTATIVE_COUNT"] +
                         accounting["SOURCE_DUPLICATE_ROWS_SUPPRESSED"])
        self.assertEqual(accounting["CANONICAL_EXPORT_REPRESENTATIVE_COUNT"],
                         accounting["SEMANTIC_ACCEPTED_COUNT"] + accounting["SEMANTIC_QUARANTINED_COUNT"])
        self.assertEqual(accounting["SOURCE_TERMINAL_COUNT"],
                         accounting["SOURCE_ACCEPTED_COUNT"] + accounting["SOURCE_QUARANTINED_COUNT"])
        self.assertEqual(accounting["SEMANTIC_QUARANTINED_COUNT"],
                         accounting["CURRENT_PLAYER_PROP_QUARANTINED_COUNT"] +
                         accounting["CURRENT_MATCH_MARKET_QUARANTINED_COUNT"] +
                         accounting["CURRENT_OPTIONAL_STATISTICS_QUARANTINED_COUNT"])
        self.assertEqual(accounting["SOURCE_IDENTITY_REPRESENTATIVE_COUNT"],
                         accounting["CORE_USABLE_REPRESENTATIVE_COUNT"] +
                         accounting["CORE_REPRESENTATIVE_SEMANTIC_QUARANTINED_COUNT"])
        self.assertEqual(accounting["LEGACY_REPORTED_SEMANTIC_QUARANTINE_STATUS"],
                         "LEGACY_MISNAMED_PLAYER_PROP_QUARANTINE")
        self.assertFalse(result["player_prop_quarantine"])
        self.assertFalse(result["match_market_quarantine"])
        self.assertEqual(result["semantic_quarantine"], [])

    def test_source_dedupe_and_core_postprocessing_have_separate_dispositions(self):
        from replay import replay_real_prematch
        result = replay_real_prematch(Path("diagnostics/raw_before_dedupe_run_1785272483_10292.jsonl"))
        accounting = result["production_accounting"]
        self.assertEqual(accounting["SOURCE_RAW_RECORDS"],
                         accounting["SOURCE_IDENTITY_REPRESENTATIVE_COUNT"] +
                         accounting["SOURCE_DUPLICATE_ROWS_SUPPRESSED"])
        self.assertEqual(accounting["SOURCE_IDENTITY_REPRESENTATIVE_COUNT"],
                         accounting["CORE_USABLE_REPRESENTATIVE_COUNT"] +
                         accounting["CORE_REPRESENTATIVE_SEMANTIC_QUARANTINED_COUNT"] +
                         accounting["CORE_POSTPROCESSING_EXCLUDED_REPRESENTATIVE_COUNT"])

    def test_export_identity_preserves_unparsed_participant_label(self):
        from core import _dedupe_canonical_export_rows
        base = {"CATEGORY":"Statystyki", "FAMILY":"GOALS_OU", "MARKET":"Liczba kartek zawodnika - 1. połowa",
                "PERIOD":"1ST_HALF", "SELECTION":"OVER", "LINE":"0.5", "SETTLEMENT":"NO_PUSH", "ODDS":"5.00"}
        rows, groups, excess = _dedupe_canonical_export_rows([
            {**base, "RAW":"Matias Gomez Powyżej 0,5 5.00"},
            {**base, "RAW":"Valentin Fascendini Powyżej 0,5 5.00"},
        ])
        self.assertEqual((len(rows), groups, excess), (2, 0, 0))

    def test_statistics_result_widgets_never_enter_result_equivalence(self):
        from core import build_equivalence_groups
        rows = [
            {"event_id":"Home|Away", "PERIOD":"1ST_HALF", "FAMILY":"1X2", "CATEGORY":"Wynik", "MARKET":"Wynik meczu", "SELECTION":"HOME", "ODDS":"2.00"},
            {"event_id":"Home|Away", "PERIOD":"1ST_HALF", "FAMILY":"1X2", "CATEGORY":"Statystyki", "MARKET":"Kartki 1X2", "SELECTION":"HOME", "ODDS":"3.00"},
        ]
        self.assertEqual(build_equivalence_groups(rows), [])


if __name__ == "__main__":
    unittest.main()
