"""Live 2026-10-25 (FC Midtjylland - Lyngby BK): compound selections use short names.

Betclic labels "Podwójna szansa & ..." and "Wynik i kto zdobędzie 1. bramkę"
selections with short team names ("Midtjylland / Lyngby & Tak"), so they were
left as raw text (MIDTJYLLAND_/_LYNGBY_&_TAK, no line).  Whole components now
resolve like double-chance and half/full components; "BK", "IF", "FF" and
"FK" are bounded club abbreviations.  Foreign or partial names never match.
"""
import unittest

from parser import parse_market_record

HOME, AWAY = "FC Midtjylland", "Lyngby BK"


def parse(title, selection):
    row, issue = parse_market_record(
        category="Wynik", market_title=title, raw_selection=selection, odds_str="2.00",
        raw_text=f"{selection} 2.00", section_title="", home_team=HOME, away_team=AWAY, container_id="c")
    assert issue is None, issue
    return row["SELECTION"], row["LINE"], row["PERIOD"]


class ShortTeamNamesInCompounds(unittest.TestCase):
    DC_BTTS = "Podwójna szansa & oba zespoły strzelą"
    DC_TOTAL = "Podwójna szansa & powyżej/poniżej"
    FIRST = "Wynik i kto zdobędzie 1. bramkę"

    def test_live_rows(self):
        self.assertEqual(parse(self.DC_BTTS, "Midtjylland / Lyngby & Tak"), ("DC_HOME_AWAY_AND_BTTS_YES", "", "FULL_TIME"))
        self.assertEqual(parse(self.DC_TOTAL, "Midtjylland / Lyngby & Powyżej 1,5"), ("DC_HOME_AWAY_AND_OVER", "1.5", "FULL_TIME"))
        self.assertEqual(parse("Podwójna szansa, obie drużyny zdobywają gole - 1. połowa", "Midtjylland / Lyngby & Nie"),
                         ("DC_HOME_AWAY_AND_BTTS_NO", "", "1ST_HALF"))
        self.assertEqual(parse(self.FIRST, "Midtjylland / Midtjylland strzeli pierwszy"), ("HOME_RESULT_AND_HOME_FIRST", "", "FULL_TIME"))
        self.assertEqual(parse(self.FIRST, "Lyngby / Midtjylland strzeli pierwszy"), ("AWAY_RESULT_AND_HOME_FIRST", "", "FULL_TIME"))

    def test_full_names_still_work(self):
        self.assertEqual(parse(self.FIRST, "FC Midtjylland / Lyngby BK strzeli pierwszy")[0], "HOME_RESULT_AND_AWAY_FIRST")

    def test_foreign_or_partial_names_are_not_guessed(self):
        for selection in ("Brondby / Lyngby & Tak", "Mid / Lyngby & Tak", "Lyngby BK Kopenhaga / Remis & Tak"):
            self.assertFalse(parse(self.DC_BTTS, selection)[0].startswith("DC_"), selection)
        self.assertFalse(parse(self.FIRST, "Odense / Lyngby strzeli pierwszy")[0].endswith("_FIRST"))


if __name__ == "__main__":
    unittest.main()
