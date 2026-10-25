"""Live 2026-10-25 Eintracht Braunschweig - Hannover 96 regressions.

The page title carries "Hannover 96".  Stripping the club number made the
away team "Hannover", which broke native short-name evidence, left the away
1X2/double-chance outcomes raw, and let the substring "over" in "Hannover"
classify away corner/card/shot totals as goal totals and read "96" as a line.
"""
import unittest

from parser import clean_team_name, parse_market_record

HOME, AWAY = "Eintracht Braunschweig", "Hannover 96"
NATIVE = {"schema": "NATIVE_EVENT_TEAM_NAMES_V1", "event_id": "1", "home": HOME, "away": AWAY,
          "home_short": "Eintracht Braun.", "away_short": "Hannover", "snapshot_sha256": "a" * 64}


def parse(title, selection, section="", home=HOME, away=AWAY):
    record, unresolved = parse_market_record(
        category="Wszystkie", market_title=title, raw_selection=selection, odds_str="2.00",
        raw_text=f"{selection} 2.00", section_title=section, home_team=home, away_team=away,
        container_id="braunschweig-hannover", native_team_names=NATIVE)
    assert record is not None, unresolved
    return record


class BraunschweigHannoverTest(unittest.TestCase):
    def test_club_number_is_part_of_the_team_name(self):
        self.assertEqual(clean_team_name("Hannover 96"), "Hannover 96")
        self.assertEqual(clean_team_name("Schalke 04"), "Schalke 04")
        self.assertEqual(clean_team_name("Arsenal 2"), "Arsenal")

    def test_fragmented_away_name_resolves_to_away(self):
        record = parse("Wynik meczu (z wyłączeniem dogrywki)", "Hannove r 96")
        self.assertEqual((record["FAMILY"], record["SELECTION"]), ("1X2", "AWAY"))

    def test_away_event_totals_are_not_goal_totals(self):
        for title, selection, direction, line in (
                ("Rzuty rożne (bez dogrywki) - Hannover 96", "Powyżej 3,5", "OVER", "3.5"),
                ("Kartki - Hannover 96", "Poniżej 1,5", "UNDER", "1.5"),
                ("Liczba strzałów w meczu (OPTA) - Hannover 96", "Poniżej 11,5", "UNDER", "11.5")):
            record = parse(title, selection)
            self.assertEqual((record["FAMILY"], record["OWNER"], record["SELECTION"], record["LINE"]),
                             ("EVENT_TOTAL", AWAY, direction, line), title)

    def test_team_name_containing_over_is_not_a_line(self):
        for title, selection in (("Zawodnik strzeli gola i zaliczy asystę", "GOAL_AND_ASSIST"),
                                 ("Zawodnik strzeli więcej goli niż drużyna przeciwna (90 min)",
                                  "OUTSCORES_OPPONENT")):
            record = parse(title, "Mustapha Bundu", section=AWAY)
            self.assertEqual((record["OWNER"], record["SELECTION"], record["LINE"]), (AWAY, selection, ""))

    def test_short_and_full_names_resolve_in_double_chance_compounds(self):
        expected = {
            ("Podwójna Szansa", "Remis lub Hannover 96"): "X2",
            ("Podwójna Szansa", "Eintracht Braun. lub Hannover"): "12",
            ("Podwójna szansa & oba zespoły strzelą", "Hannover 96 / Remis & Tak"): "DC_AWAY_DRAW_AND_BTTS_YES",
            ("Wynik Meczu Połowa / Cały", "Eintracht Braunschweig / Hannover 96"): "HOME_AWAY",
            ("Wynik i kto zdobędzie 1. bramkę", "Hannover / Eintracht Braun. strzeli pierwszy"):
                "AWAY_RESULT_AND_HOME_FIRST",
        }
        for (title, selection), canonical in expected.items():
            self.assertEqual(parse(title, selection)["SELECTION"], canonical, selection)

    def test_whole_word_over_under_still_parse(self):
        record = parse("Gole Powyżej/Poniżej", "Powyżej 2,5")
        self.assertEqual((record["FAMILY"], record["SELECTION"], record["LINE"]), ("GOALS_OU", "OVER", "2.5"))
        record = parse("Liczba strzałów zawodnika (OPTA)", "Yann Sturm Powyżej 3,5")
        self.assertEqual((record["SELECTION"], record["LINE"]), ("OVER", "3.5"))


if __name__ == "__main__":
    unittest.main()
