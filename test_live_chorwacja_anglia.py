"""Live 2026-10-02 (Chorwacja - Anglia, FAST6): "I. Perisic" lost its initial.

Player lists were split on the conjunction "i" case-insensitively, so the
initial "I." of "I. Perisic" was taken as a separator (". Perisic").  A
conjunction is a lowercase word between spaces; an initial never separates.
"""
import unittest

from parser import parse_market_record


def participants(title, selection, section="Chorwacja"):
    row, issue = parse_market_record(
        category="Strzelcy", market_title=title, raw_selection=selection, odds_str="15",
        raw_text=f"{selection} 15", section_title=section, home_team="Chorwacja", away_team="Anglia",
        container_id="c")
    assert issue is None, issue
    return row.get("PARTICIPANTS") or [row.get("PARTICIPANT")]


class InitialIsNotAConjunction(unittest.TestCase):
    PAIR = "Strzelec bramki i zawodnik, który zaliczy przy niej asystę (czas reg.)"

    def test_scorer_and_assister_keep_the_initial(self):
        for joiner in (" i ", " & ", " / "):
            self.assertEqual(participants(self.PAIR, f"D. Beljo (G){joiner}I. Perisic (A)"),
                             ["D. Beljo (G)", "I. Perisic (A)"], joiner)

    def test_lowercase_conjunctions_still_separate(self):
        self.assertEqual(participants(self.PAIR, "A. Budimir i H. Kane"), ["A. Budimir", "H. Kane"])
        self.assertEqual(participants(self.PAIR, "H. Kane oraz A. Gordon"), ["H. Kane", "A. Gordon"])

    def test_single_scorer_with_initial_i(self):
        self.assertEqual(participants("Strzelec", "I. Perisic"), ["I. Perisic"])


if __name__ == "__main__":
    unittest.main()
