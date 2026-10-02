"""Live 2026-10-02 (Francja - Wlochy, FAST4): three Top cards had no header.

"wygra mecz bez straty gola", "strzeli gola w drugiej połowie meczu" and the
player shots card without "(OPTA)" left the capture PARTIAL.  Each is a
complete, self-describing sentence; the plain Top outcome sentences are
recovered the same way, with exact team identity.
"""
import unittest

from core import partition_semantic_records
from parser import parse_market_record, recover_headerless_top_offer

INSTANCE = ("tab:Top|sports-markets-single-market[block.marketElement#0]|"
            "div[marketBox.is-goodDeals#0]|sports-matrix-markets[#1]|row#0")
HOME, AWAY = "Francja", "Włochy"


def parse(text):
    recovered = recover_headerless_top_offer(text, "Top", INSTANCE, HOME, AWAY)
    if recovered is None:
        return None
    row, issue = parse_market_record(
        category="Top", market_title=recovered["market_title"], raw_selection=recovered["raw_selection"],
        odds_str="2.00", raw_text=f"{text} 2.00", section_title="", home_team=HOME, away_team=AWAY,
        participant_hint=recovered.get("participant_hint"), container_id=INSTANCE,
        market_instance_id=INSTANCE, main_tab="Top", raw_record_id="r", source_raw_record_ids=["r"])
    assert issue is None, issue
    return row


class FrancjaWlochyTopCards(unittest.TestCase):
    def assertAccepted(self, text, family, period, selection, owner=""):
        row = parse(text)
        self.assertIsNotNone(row, text)
        self.assertEqual((row["FAMILY"], row["PERIOD"], row["SELECTION"]), (family, period, selection), text)
        if owner:
            self.assertEqual(row["OWNER"], owner)
        self.assertEqual(partition_semantic_records([row]), ([row], []), text)

    def test_the_three_live_cards_are_no_longer_unresolved(self):
        self.assertAccepted("Francja wygra mecz bez straty gola", "TEAM_WIN_TO_NIL", "FULL_TIME", "YES", "Francja")
        self.assertAccepted("Michael Olise strzeli gola w drugiej połowie meczu", "GOALSCORER", "2ND_HALF", "Michael Olise")
        shots = parse("Francesco Esposito powyżej 0,5 celnych strzałów na bramkę")
        self.assertEqual((shots["FAMILY"], shots["SELECTION"], shots["LINE"]), ("PLAYER_PROP", "OVER", "0.5"))
        self.assertEqual(partition_semantic_records([shots])[0], [])

    def test_plain_top_outcome_sentences(self):
        self.assertAccepted("Francja wygra mecz", "1X2", "FULL_TIME", "HOME")
        self.assertAccepted("Remis w meczu", "1X2", "FULL_TIME", "DRAW")
        self.assertAccepted("Włochy wygra drugą połowę meczu", "1X2", "2ND_HALF", "AWAY")
        self.assertAccepted("Obie drużyny strzelą gola w meczu", "BTTS", "FULL_TIME", "TAK")
        self.assertAccepted("Francja strzeli gola w meczu", "TEAM_TOTALS_HOME", "FULL_TIME", "OVER")
        self.assertAccepted("Kylian Mbappe strzeli gola w meczu", "GOALSCORER", "FULL_TIME", "Kylian Mbappe")

    def test_unknown_team_or_group_is_not_guessed(self):
        for text in ("Hiszpania wygra mecz", "Hiszpania wygra mecz bez straty gola",
                     "Francja i Włochy strzelą gola w meczu", "Francja lub Włochy wygra mecz"):
            self.assertIsNone(recover_headerless_top_offer(text, "Top", INSTANCE, HOME, AWAY), text)

    def test_substitute_card_keeps_its_own_market(self):
        recovered = recover_headerless_top_offer("Michael Olise lub jego zmiennik strzeli gola w meczu",
                                                 "Top", INSTANCE, HOME, AWAY)
        self.assertEqual(recovered["market_title"], "Strzelec gola lub jego zmiennik")


if __name__ == "__main__":
    unittest.main()
