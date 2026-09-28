"""Regressions from the live release test Szwecja - Polska (2026-09-28).

1. A bare "Wynik" card priced 5.00 / 1.30 / 7.75 (an interval result) was
   classified as the full-time 1X2 through the canonical-family default and
   produced false "better price" alerts against the real FT result
   1.93 / 3.78 / 3.73.
2. Self-describing Top cards without a header left the capture PARTIAL.
3. The release self-test reported FAIL for a capture whose only gaps were
   explicitly quarantined offers.
"""
import unittest

from apex_context_engine.engine import build_context
from apex_context_engine.market_graph import best_price_alerts, equivalence_price_contradictions
from apex_context_engine.packet_parser import parse_packet_text
from apex_context_engine.report import render_match_context
from core import _semantic_quarantine_reason
from parser import classify_period_detail, parse_market_record, recover_headerless_top_offer
from release_self_test import _verdict
from test_package_context_quarantine import odd, with_odds

HOME, AWAY = "Szwecja", "Polska"
TOP_INSTANCE = ("tab:Top|sports-markets-single-market[block.marketElement#0]|"
                "div[marketBox.is-goodDeals#0]|sports-matrix-markets[#1]|row#0")


def parse(title, selection, odds, section="", ancestor="", hint="", category="Wynik"):
    record, issue = parse_market_record(
        category=category, market_title=title, raw_selection=selection, odds_str=odds,
        raw_text=f"{selection} {odds}", section_title=section, home_team=HOME, away_team=AWAY,
        container_id="c", period_hint=hint, ancestor_title=ancestor, main_tab=category)
    return record


class BareResultTitleIsNotFullTime(unittest.TestCase):
    def test_live_bare_wynik_rows_are_quarantined_not_full_time(self):
        for selection, odds in ((HOME, "5.00"), ("Remis", "1.30"), (AWAY, "7.75")):
            record = parse("Wynik", selection, odds)
            self.assertEqual(record["FAMILY"], "1X2")
            self.assertEqual((record["PERIOD"], record["PERIOD_SOURCE"]),
                             ("UNKNOWN", "GENERIC_RESULT_TITLE_WITHOUT_PERIOD"))
            self.assertEqual(_semantic_quarantine_reason(record), "UNCONFIRMED_MARKET_PERIOD")

    def test_real_full_time_result_is_unchanged(self):
        for title in ("Wynik meczu (z wyłączeniem dogrywki)", "Wynik meczu"):
            record = parse(title, AWAY, "3.73")
            self.assertEqual((record["FAMILY"], record["PERIOD"], record["SELECTION"]), ("1X2", "FULL_TIME", "AWAY"))
            self.assertEqual(_semantic_quarantine_reason(record), "")

    def test_bare_wynik_with_explicit_half_keeps_its_half(self):
        self.assertEqual(parse("Wynik", "Remis", "2.10", section="1. połowa")["PERIOD"], "1ST_HALF")
        self.assertEqual(parse("Wynik", "Remis", "2.10", ancestor="2. połowa")["PERIOD"], "2ND_HALF")

    def test_time_window_evidence_never_defaults_to_full_time(self):
        for kwargs in ({"section": "0-15 min"}, {"section": "0–15 min"}, {"ancestor": "00:00 - 14:59"},
                       {"hint": "Pierwsze 10 minut"}, {"section": "do 30. minuty"}):
            for title in ("Wynik", "Wynik meczu", "Podwójna szansa"):
                record = parse(title, "Remis" if title != "Podwójna szansa" else "1X", "1.30", **kwargs)
                self.assertEqual(record["PERIOD"], "UNKNOWN", (title, kwargs))
                self.assertTrue(record["PERIOD_SOURCE"].startswith("UNSUPPORTED_TIME_WINDOW:"), (title, kwargs))

    def test_documented_minute_contracts_keep_their_meaning(self):
        self.assertEqual(classify_period_detail("Wynik meczu (90 min)", "", family="1X2")[0], "FULL_TIME")
        self.assertEqual(classify_period_detail("1X2 strzały (120 min)", "", family="1X2")[0],
                         "MATCH_INCLUDING_EXTRA_TIME")
        self.assertEqual(classify_period_detail("Wynik (30 min)", "", family="1X2")[0], "OTHER")


class PriceContradictionIsNotABetterPrice(unittest.TestCase):
    def packet(self):
        rows = [odd(MARKET="Wynik meczu (z wyłączeniem dogrywki)", SELECTION=s, OWNER=o, ODDS=p, RAW=f"x {p}")
                for s, o, p in (("HOME", HOME, "1.93"), ("DRAW", "", "3.78"), ("AWAY", AWAY, "3.73"))]
        rows += [odd(MARKET="Wynik", CATEGORY="Wynik", SELECTION=s, OWNER=o, ODDS=p, RAW=f"x {p}")
                 for s, o, p in (("HOME", HOME, "5.00"), ("DRAW", "", "1.30"), ("AWAY", AWAY, "7.75"))]
        return parse_packet_text(with_odds(*rows))

    def test_contradicting_equivalent_prices_are_reported_not_alerted(self):
        parsed = self.packet()
        self.assertEqual([a for a in best_price_alerts(parsed.odds)
                          if any(c["gain_percent"] > 50 for c in a["worse_copies"])], [])
        contradictions = equivalence_price_contradictions(parsed.odds)
        self.assertEqual({row["signature"] for row in contradictions},
                         {"FOOTBALL_RESULT|FULL_TIME|RESULT_HOME", "FOOTBALL_RESULT|FULL_TIME|RESULT_AWAY"})
        context = build_context(parsed)
        self.assertEqual([a for a in context.best_price_alerts if a["best"]["market"] == "Wynik"], [])
        self.assertIn("EQUIVALENCE_PRICE_CONTRADICTION", {a["type"] for a in context.anomalies})
        report = render_match_context(context)
        self.assertIn("PRICE_CONTRADICTIONS=2", report)
        better = report.split("[BETTER_PRICE_SAME_SETTLEMENT]", 1)[-1].split("[DATA_QUALITY]", 1)[0]
        self.assertNotIn("Wynik 7.75 vs", better)
        self.assertNotIn("Wynik 5.0 vs", better)

    def test_ordinary_price_differences_still_alert(self):
        rows = [odd(MARKET="Wynik meczu (z wyłączeniem dogrywki)", SELECTION="AWAY", OWNER=AWAY, ODDS="3.73", RAW="x 3.73"),
                odd(MARKET="Handicap (2-drożny)", FAMILY="HANDICAP_EUROPEAN", HANDICAP_KIND="TWO_WAY",
                    SELECTION="AWAY", OWNER=AWAY, LINE="-0.5", SETTLEMENT="NO_PUSH", ODDS="3.90", RAW="x 3.90")]
        parsed = parse_packet_text(with_odds(*rows))
        self.assertEqual(equivalence_price_contradictions(parsed.odds), [])


class LiveHeaderlessTopCards(unittest.TestCase):
    def test_closed_grammar_rows_recover(self):
        corners = recover_headerless_top_offer("Powyżej 9,5 rzutów rożnych w meczu", "Top", TOP_INSTANCE, HOME, AWAY)
        record = parse(corners["market_title"], corners["raw_selection"], "1.98", category="Top")
        self.assertEqual((record["FAMILY"], record["PERIOD"], record["SELECTION"], record["LINE"]),
                         ("EVENT_TOTAL", "FULL_TIME", "OVER", "9.5"))
        draw = recover_headerless_top_offer("Remis po pierwszej połowie meczu", "Top", TOP_INSTANCE, HOME, AWAY)
        record = parse(draw["market_title"], draw["raw_selection"], "2.38", category="Top")
        self.assertEqual((record["FAMILY"], record["PERIOD"], record["SELECTION"]), ("1X2", "1ST_HALF", "DRAW"))

    def test_unproven_rows_stay_unresolved(self):
        for text in ("Mateusz Żukowski lub jego zmiennik powyżej 1,5 strzałów na bramkę",
                     "W meczu padnie gol strzelony głową", "Jan Bednarek powyżej 0,5 kartki w meczu"):
            self.assertIsNone(recover_headerless_top_offer(text, "Top", TOP_INSTANCE, HOME, AWAY), text)

    def test_recovery_requires_the_top_matrix_boundary(self):
        self.assertIsNone(recover_headerless_top_offer("Remis po pierwszej połowie meczu", "Wynik", TOP_INSTANCE))
        self.assertIsNone(recover_headerless_top_offer("Remis po pierwszej połowie meczu", "Top", "tab:Top|div[x#0]"))


class ReleaseSelfTestVerdict(unittest.TestCase):
    BASE = dict(odds_count=1136, context_status="PASS_WITH_QUARANTINE", products_distinct=True,
                products_clean=True, quarantine_explained=True)

    def test_complete_capture_passes(self):
        self.assertEqual(_verdict(dict(self.BASE, extract_status="GOTOWE", unresolved_count=0))["verdict"], "PASS")

    def test_explained_content_quarantine_passes_with_warnings(self):
        result = _verdict(dict(self.BASE, extract_status="PARTIAL", unresolved_count=5,
                               incomplete_reasons=["UNRESOLVED", "PERIOD_UNKNOWN"]))
        self.assertEqual((result["verdict"], result["passed"]), ("PASS_WITH_WARNINGS", True))

    def test_structural_gaps_or_dirty_products_fail(self):
        for override in ({"incomplete_reasons": ["UNRESOLVED", "REMAINING_MORE"]},
                         {"incomplete_reasons": ["UNACCOUNTED_PRICED_CANDIDATES"]},
                         {"quarantine_explained": False}, {"products_clean": False},
                         {"products_distinct": False}, {"context_status": "FAIL"}, {"odds_count": 0},
                         {"extract_status": "BŁĄD"}):
            report = dict(self.BASE, extract_status="PARTIAL", unresolved_count=5, incomplete_reasons=["UNRESOLVED"])
            report.update(override)
            result = _verdict(report)
            self.assertEqual((result["verdict"], result["passed"]), ("FAIL", False), override)


if __name__ == "__main__":
    unittest.main()
