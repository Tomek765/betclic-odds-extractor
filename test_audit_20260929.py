"""Regressions from the 2026-09-29 full audit of four consecutive live matches."""
import unittest

from apex_context_engine.anomalies import line_policy
from apex_context_engine.engine import build_context
from apex_context_engine.packet_parser import parse_packet_text
from test_package_context_quarantine import odd, with_odds


def suspicious_lines(*rows):
    context = build_context(parse_packet_text(with_odds(*rows)))
    return [a["evidence"] for a in context.anomalies if a["type"] == "SUSPICIOUS_LINE"]


class BookingPointsAreNotCardCounts(unittest.TestCase):
    """Every audited match raised 4 false SUSPICIOUS_LINE alerts for 1H booking points 25.5 / 35.5."""

    def row(self, market, line, family="EVENT_TOTAL", period="1ST_HALF", selection="OVER"):
        return odd(CATEGORY="Statystyki", FAMILY=family, MARKET=market, PERIOD=period, SELECTION=selection,
                   LINE=line, SETTLEMENT="NO_PUSH", ODDS="2.00", RAW=f"{selection} {line} 2.00")

    def test_realistic_booking_points_lines_are_not_suspicious(self):
        rows = [self.row("Punkty za kartki Powyżej/Poniżej - 1. połowa", line) for line in ("5.5", "15.5", "25.5", "35.5")]
        rows += [self.row("Punkty za kartki Powyżej/Poniżej", line, period="FULL_TIME") for line in ("35.5", "45.5", "65.5")]
        self.assertEqual(suspicious_lines(*rows), [])

    def test_absurd_booking_points_are_still_flagged(self):
        flagged = suspicious_lines(self.row("Punkty za kartki Powyżej/Poniżej - 1. połowa", "400.5"))
        self.assertEqual([row["line"] for row in flagged], ["400.5"])

    def test_card_counts_keep_their_original_ceiling(self):
        flagged = suspicious_lines(self.row("Liczba Kartek 1. połowa", "25.5"))
        self.assertEqual([row["line"] for row in flagged], ["25.5"])
        self.assertEqual(suspicious_lines(self.row("Liczba Kartek 1. połowa", "3.5")), [])


if __name__ == "__main__":
    unittest.main()


class CaseOnlyTitleDuplicatesAreListedOnce(unittest.TestCase):
    def test_same_bet_under_two_title_spellings_is_one_row(self):
        from apex_context_engine.llm_format import render_llm_odds
        header = {"MATCH": "A - B", "COMPETITION": "L", "KICKOFF": "20:00"}
        base = dict(FAMILY="DOUBLE_CHANCE", PERIOD="FULL_TIME", OWNER="", SELECTION="1X", LINE="", ODDS="1.29",
                    SETTLEMENT="WIN_LOSE", RAW="1X 1.29")
        text = render_llm_odds(header, [dict(base, MARKET="Podwójna Szansa"), dict(base, MARKET="Podwójna  szansa")])
        rows = [line for line in text.splitlines() if line.startswith("DOUBLE_CHANCE|")]
        self.assertEqual(rows, ["DOUBLE_CHANCE|Podwójna Szansa|FULL_TIME||1X||1.29|WIN_LOSE"])
        self.assertIn("ODDS_COUNT=1", text)

    def test_different_price_or_selection_is_never_merged(self):
        from apex_context_engine.llm_format import render_llm_odds
        header = {"MATCH": "A - B", "COMPETITION": "L", "KICKOFF": "20:00"}
        base = dict(FAMILY="DOUBLE_CHANCE", PERIOD="FULL_TIME", OWNER="", LINE="", SETTLEMENT="WIN_LOSE", MARKET="Podwójna szansa")
        rows = [dict(base, SELECTION="1X", ODDS="1.29", RAW="1X 1.29"), dict(base, SELECTION="X2", ODDS="1.29", RAW="X2 1.29"),
                dict(base, SELECTION="1X", ODDS="1.31", RAW="1X 1.31", MARKET="Podwójna Szansa")]
        text = render_llm_odds(header, rows)
        self.assertIn("ODDS_COUNT=3", text)

    def test_different_source_text_keeps_each_offer(self):
        from apex_context_engine.llm_format import render_llm_odds
        header = {"MATCH": "A - B", "COMPETITION": "L", "KICKOFF": "20:00"}
        base = dict(FAMILY="DOUBLE_CHANCE", PERIOD="FULL_TIME", OWNER="", SELECTION="1X", LINE="", ODDS="1.29",
                    SETTLEMENT="WIN_LOSE")
        text = render_llm_odds(header, [dict(base, MARKET="Podwójna Szansa", RAW="1X 1.29"),
                                        dict(base, MARKET="Podwójna szansa", RAW="Walia lub Remis 1.29")])
        self.assertIn("ODDS_COUNT=2", text)
        self.assertEqual(text.count("|RAW="), 2)


class PolishLetterIsNotDroppedFromCompoundTokens(unittest.TestCase):
    """Live Niemcy - Serbia: 'Żaden zespół nie strzeli' became ZADEN_ZESPO_NIE_STRZELI; 'Włochy' would be WOCHY."""

    def parse(self, title, selection, home="Turcja", away="Włochy"):
        from parser import parse_market_record
        row, issue = parse_market_record(
            category="Wynik", market_title=title, raw_selection=selection, odds_str="3.00",
            raw_text=f"{selection} 3.00", section_title="", home_team=home, away_team=away, container_id="c")
        self.assertIsNone(issue)
        return row

    def test_team_name_with_l_stroke_keeps_all_letters(self):
        for title in ("Wynik meczu & oba zespoły strzelą", "Wynik/oba zespoły strzelą - 1. połowa"):
            self.assertEqual(self.parse(title, "Włochy / Tak")["SELECTION"], "WLOCHY_/_TAK")
            self.assertEqual(self.parse(title, "Włochy / Nie")["SELECTION"], "WLOCHY_/_NIE")
            self.assertEqual(self.parse(title, "Turcja / Tak")["SELECTION"], "TURCJA_/_TAK")

    def test_no_goal_option_keeps_its_letters(self):
        row = self.parse("Wynik i kto zdobędzie 1. bramkę", "Remis / Żaden zespół nie strzeli")
        self.assertEqual(row["SELECTION"], "REMIS_/_ZADEN_ZESPOL_NIE_STRZELI")

    def test_recognised_forms_are_unchanged(self):
        self.assertEqual(self.parse("Wynik i kto zdobędzie 1. bramkę", "Włochy / Turcja strzeli pierwszy")["SELECTION"],
                         "AWAY_RESULT_AND_HOME_FIRST")
        self.assertEqual(self.parse("Wynik Meczu Połowa / Cały", "Włochy / Włochy")["SELECTION"], "AWAY_AWAY")


class QuarantineNamesItsMarkets(unittest.TestCase):
    def test_data_quality_lists_the_markets_behind_each_reason(self):
        from apex_context_engine.report import render_match_context
        rows = [odd(FAMILY="GOAL_MARGIN", MARKET="Różnica goli", SELECTION="Remis", SETTLEMENT="UNKNOWN", ODDS="4.00", RAW="Remis 4.00"),
                odd(FAMILY="GOAL_MARGIN", MARKET="Różnica goli", SELECTION="Bez goli", SETTLEMENT="UNKNOWN", ODDS="9.00", RAW="Bez goli 9.00")]
        context = build_context(parse_packet_text(with_odds(*rows)))
        report = render_match_context(context)
        quality = report.split("[DATA_QUALITY]", 1)[1]
        self.assertIn("QUARANTINED_BETS=2", quality)
        self.assertRegex(quality, r"QUARANTINED_MARKETS \S+: Różnica goli x2")

    def test_clean_capture_has_no_market_lines(self):
        from apex_context_engine.report import render_match_context
        report = render_match_context(build_context(parse_packet_text(with_odds(odd()))))
        self.assertNotIn("QUARANTINED_MARKETS", report)


class SelfDescribingHiddenOptionsAreAccepted(unittest.TestCase):
    """Exact labels from the live Independiente Medellin - Millonarios quarantine (13 rows)."""

    def parse(self, title, selection, home="Independiente Medellin", away="Millonarios"):
        from core import _semantic_quarantine_reason
        from parser import parse_market_record
        row, issue = parse_market_record(
            category="Wynik", market_title=title, raw_selection=selection, odds_str="5.00",
            raw_text=f"{selection} 5.00", section_title="", home_team=home, away_team=away, container_id="c")
        self.assertIsNone(issue)
        return row, _semantic_quarantine_reason(row)

    def test_clear_options_are_accepted(self):
        for title, selection in (
                ("Liczba goli - 1. połowa", "Brak Gola"), ("Liczba goli - 2. połowa", "Brak Gola"),
                ("Czas 1. gola", "80:00 - Koniec meczu (90min)"), ("Czas 1. gola", "Brak Gola"),
                ("Czas 1. gola - opcja II", "Przerwa - 59:59"),
                ("Czas 1. gola - opcja II", "75:00 - Koniec meczu (90min)"),
                ("Czas 1. gola - opcja II", "Brak Gola"),
                ("Dokładny wynik w grupie", "3 - 2, 4 - 2, 4 - 3 lub 5 - 1"),
                ("Dokładny wynik w grupie", "2 - 3, 2 - 4, 3 - 4 lub 1 - 5"),
                ("Różnica goli", "Remis")):
            row, reason = self.parse(title, selection)
            self.assertEqual((reason, row["SETTLEMENT"]), ("", "WIN_LOSE"), (title, selection))

    def test_labels_that_depend_on_other_groups_stay_quarantined(self):
        for selection in ("Independiente Medellin - Inny wynik", "Millonarios - Inny wynik", "Remis"):
            row, reason = self.parse("Dokładny wynik w grupie", selection)
            self.assertEqual(reason, "UNCONFIRMED_MARKET_SETTLEMENT", selection)

    def test_previously_accepted_shapes_and_junk_are_unchanged(self):
        from parser import is_correct_score_group_selection as ok
        for good in ("1 - 0, 2 - 0 lub 3 - 0", "4 - 0, 5 - 0 lub 6 - 0", "0-1, 0-2, 0-3"):
            self.assertTrue(ok(good), good)
        for bad in ("1 - 0", "1 - 0 lub 2 - 0", "1 - 0, 2 - 0", "Remis", "Inny wynik", "1 - 0, 2 - 0 lub Remis",
                    "1 - 0 2 - 0 lub 3 - 0", ""):
            self.assertFalse(ok(bad), bad)
        for title, selection in (("Czas 1. gola", "80:00 - Koniec"), ("Czas 1. gola", "80:00 - Koniec meczu (120min)"),
                                 ("Czas 1. gola", "Przerwa - Przerwa"), ("Liczba goli - 1. połowa", "Brak"),
                                 ("Różnica goli", "Remis lub Serbia")):
            _row, reason = self.parse(title, selection)
            self.assertEqual(reason, "UNCONFIRMED_MARKET_SETTLEMENT", (title, selection))

    def test_context_engine_takes_the_new_options_without_side_effects(self):
        base = [odd()]
        added = [odd(FAMILY="GOAL_RANGE", MARKET="Liczba goli - 1. połowa", PERIOD="1ST_HALF", SELECTION="Brak Gola", SETTLEMENT="WIN_LOSE", ODDS="3.40", RAW="Brak Gola 3.40"),
                 odd(FAMILY="FIRST_GOAL_TIME", MARKET="Czas 1. gola", SELECTION="80:00 - Koniec meczu (90min)", SETTLEMENT="WIN_LOSE", ODDS="9.00", RAW="x 9.00"),
                 odd(FAMILY="GOAL_MARGIN", MARKET="Różnica goli", SELECTION="Remis", SETTLEMENT="WIN_LOSE", ODDS="4.00", RAW="Remis 4.00"),
                 odd(FAMILY="CORRECT_SCORE_GROUP", MARKET="Dokładny wynik w grupie", SELECTION="3 - 2, 4 - 2, 4 - 3 lub 5 - 1", SETTLEMENT="WIN_LOSE", ODDS="30.00", RAW="x 30.00")]
        before = build_context(parse_packet_text(with_odds(*base)))
        after = build_context(parse_packet_text(with_odds(*base, *added)))
        self.assertEqual((after.status, after.quarantined_rows), (before.status, before.quarantined_rows))
        self.assertEqual((after.fair_markets, after.best_price_alerts), (before.fair_markets, before.best_price_alerts))
        self.assertEqual(after.accepted_rows - before.accepted_rows, 4)


class QuarantineShowsSourceContext(unittest.TestCase):
    def test_box_context_reaches_the_diagnostics_file(self):
        from apex_context_engine.report import quarantine_diagnostics
        context = build_context(parse_packet_text(with_odds(odd()) +
            '\nSEMANTIC_QUARANTINE{\nMARKET="Wynik";\nSELECTION="HOME";\nPERIOD="UNKNOWN";\n'
            'REASON="UNCONFIRMED_MARKET_PERIOD";\nRAW_RECORD_ID="run_7:43";\n'
            'BOX_CONTEXT="Wynik 0-15 min Grecja 7.25 Remis 1.29 Holandia 5.40";\n}\n'))
        rows = [r for r in quarantine_diagnostics(context) if r["market_name"] == "Wynik"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_context"], "Wynik 0-15 min Grecja 7.25 Remis 1.29 Holandia 5.40")

    def test_rows_without_context_have_an_empty_field(self):
        from apex_context_engine.report import quarantine_diagnostics
        context = build_context(parse_packet_text(with_odds(odd(ODDS="abc", RAW="x abc"))))
        self.assertTrue(all(r["source_context"] == "" for r in quarantine_diagnostics(context)))


class DomScriptCarriesTheBoxContext(unittest.TestCase):
    def test_market_box_text_is_emitted_for_every_price(self):
        try:
            from playwright.sync_api import sync_playwright
            playwright = sync_playwright().start()
            browser = playwright.chromium.launch(headless=True)
        except Exception as exc:  # pragma: no cover
            raise unittest.SkipTest(f"Chromium unavailable: {exc}")
        try:
            from core import _extract_dom_from_page
            page = browser.new_page()
            page.set_content(
                '<div class="marketBox"><h2 class="marketBox_headTitle">Wynik</h2>'
                '<span class="chip is-active">0-15 min</span>'
                '<div class="marketBox_lineSelection"><p class="marketBox_label">Remis</p>'
                '<button class="btn is-odd"><span class="oddValue">1,29</span></button></div></div>')
            records = _extract_dom_from_page(page, "Wynik")
        finally:
            browser.close()
            playwright.stop()
        self.assertEqual(len(records), 1)
        self.assertIn("0-15 min", records[0]["box_context"])
        self.assertLessEqual(len(records[0]["box_context"]), 200)


class ProductionNormalizationUsesTheSameGrammar(unittest.TestCase):
    """EXPAND4 unit tests passed while the live run still quarantined the rows: core.py held a second copy of
    _known_not_modeled_settlement and recomputes SETTLEMENT in derive_market_normalization.  These tests go through
    that production step with the exact live rows (Dania - Portugalia)."""

    HOME, AWAY = "Dania", "Portugalia"

    def through_production(self, title, selection):
        from core import _semantic_quarantine_reason, derive_market_normalization
        from parser import parse_market_record
        row, issue = parse_market_record(
            category="Wynik", market_title=title, raw_selection=selection, odds_str="5.00",
            raw_text=f"{selection} 5.00", section_title="", home_team=self.HOME, away_team=self.AWAY,
            container_id="c", source_raw_record_ids=["run_1:1"], raw_record_id="run_1:1")
        self.assertIsNone(issue)
        derive_market_normalization([row], self.HOME, self.AWAY)
        return row["FAMILY"], row["SETTLEMENT"], _semantic_quarantine_reason(row)

    def test_live_options_are_accepted_by_the_production_step(self):
        for title, selection, family in (
                ("Liczba goli - 1. połowa", "Brak Gola", "GOAL_RANGE"),
                ("Liczba goli - 2. połowa", "Brak Gola", "GOAL_RANGE"),
                ("Czas 1. gola", "80:00 - Koniec meczu (90min)", "FIRST_GOAL_TIME"),
                ("Czas 1. gola", "Brak Gola", "FIRST_GOAL_TIME"),
                ("Czas 1. gola - opcja II", "Przerwa - 59:59", "FIRST_GOAL_TIME"),
                ("Czas 1. gola - opcja II", "75:00 - Koniec meczu (90min)", "FIRST_GOAL_TIME"),
                ("Czas 1. gola - opcja II", "Brak Gola", "FIRST_GOAL_TIME"),
                ("Dokładny wynik w grupie", "3 - 2, 4 - 2, 4 - 3 lub 5 - 1", "CORRECT_SCORE_GROUP"),
                ("Różnica goli", "Remis", "GOAL_MARGIN")):
            self.assertEqual(self.through_production(title, selection), (family, "WIN_LOSE", ""), (title, selection))

    def test_labels_that_depend_on_other_groups_stay_quarantined(self):
        for selection in ("Dania - Inny wynik", "Portugalia - Inny wynik", "Remis"):
            family, settlement, reason = self.through_production("Dokładny wynik w grupie", selection)
            self.assertEqual((family, settlement, reason), ("CORRECT_SCORE_GROUP", "UNKNOWN", "UNCONFIRMED_MARKET_SETTLEMENT"))

    def test_there_is_one_settlement_grammar(self):
        import core
        import parser
        self.assertIs(core._known_not_modeled_settlement, parser._known_not_modeled_settlement)
