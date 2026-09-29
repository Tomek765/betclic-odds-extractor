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
