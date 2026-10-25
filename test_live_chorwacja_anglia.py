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


class NonGoalPlayerPropsCarryNoScorerScope(unittest.TestCase):
    """Audit 2026-10-25: 57 shots/cards/fouls/offsides/assist rows per match
    carried SCORER_SCOPE=ANYTIME, a goal-scorer scope that does not apply."""

    def scope(self, title, selection="Harry Kane Powyżej 0,5"):
        row, issue = parse_market_record(
            category="Statystyki", market_title=title, raw_selection=selection, odds_str="1.50",
            raw_text=f"{selection} 1.50", section_title="Anglia", home_team="Chorwacja", away_team="Anglia",
            container_id="c", participant_hint="Harry Kane")
        assert issue is None, issue
        return row["FAMILY"], row.get("SCORER_SCOPE", "")

    def test_non_goal_props_have_no_scope(self):
        for title in ("Liczba strzałów zawodnika (OPTA)", "Liczba celnych strzałów zawodnika (OPTA)",
                      "Liczba kartek zawodnika", "Liczba fauli zawodnika (OPTA) - 1. połowa",
                      "Liczba spalonych zawodnika (OPTA) - 1. połowa", "Zawodnik zanotuje asystę"):
            self.assertEqual(self.scope(title), ("PLAYER_PROP", ""), title)

    def test_goal_props_keep_their_scope(self):
        self.assertEqual(self.scope("Zawodnik strzeli i powyżej 1,5 goli - 1. połowa", "Harry Kane"),
                         ("PLAYER_PROP", "ANYTIME"))
        self.assertEqual(self.scope("Strzelec", "Harry Kane"), ("GOALSCORER", "ANYTIME"))
