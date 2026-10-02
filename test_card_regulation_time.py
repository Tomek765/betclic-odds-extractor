"""Card markets: proven outcome shapes, documented periods only.

Live 2026-10-02 (Wegry - Gruzja): "Czerwona kartka" / "Czerwona kartka - <team>"
had no family at all.  They are closed Tak/Nie propositions (BINARY_EVENT), but
like "Punkty za kartki Powyzej/Ponizej" and "Dokladna liczba kartek - <team>"
their duration is not documented by the Betclic terms copy
(docs/SEMANTICS_20260905.md), so they stay explicitly quarantined.  Only
"Liczba kartek", "Wiecej kartek" and "Kartki - <team>" carry the documented
regulation-time rule.
"""
import unittest

from core import _semantic_quarantine_reason, canonical_export_boundary
from parser import parse_market_record

HOME, AWAY = "Węgry", "Gruzja"


def parse(market, selection, odds="2.00", tab="Statystyki"):
    record, unresolved = parse_market_record(
        category=tab, market_title=market, raw_selection=selection, odds_str=odds,
        raw_text=f"{selection} {odds}", section_title="", home_team=HOME, away_team=AWAY,
        container_id="", main_tab=tab)
    assert record and not unresolved, (market, selection, unresolved)
    record["CATEGORY"] = tab
    return record


class RedCardMarket(unittest.TestCase):
    def test_red_card_is_a_binary_event_with_team_owner(self):
        match = parse("Czerwona kartka", "Tak")
        team = parse("Czerwona kartka - Węgry", "Nie")
        self.assertEqual((match["FAMILY"], match.get("OWNER") or "", match["SETTLEMENT"]), ("BINARY_EVENT", "", "WIN_LOSE"))
        self.assertEqual((team["FAMILY"], team["OWNER"], team["SETTLEMENT"]), ("BINARY_EVENT", HOME, "WIN_LOSE"))

    def test_red_card_duration_is_not_assumed(self):
        rows = [parse("Czerwona kartka", "Tak"), parse("Czerwona kartka - Gruzja", "Nie")]
        for index, row in enumerate(rows):
            row["source_raw_record_ids"] = [f"r:{index}"]
            self.assertEqual(row["PERIOD"], "UNKNOWN")
        _, accepted, quarantined, _, _ = canonical_export_boundary(rows, HOME, AWAY)
        self.assertEqual(accepted, [])
        self.assertEqual({_semantic_quarantine_reason(row) for row in quarantined},
                         {"UNSUPPORTED_OPTIONAL_STATISTICS_PERIOD"})


class DocumentedCardRuleOnly(unittest.TestCase):
    def test_documented_titles_are_regulation_time(self):
        for market, selection in (("Liczba kartek", "Powyżej 3,5"), ("Więcej kartek", "Węgry"),
                                  ("Kartki - Węgry", "Powyżej 1,5")):
            with self.subTest(market=market):
                record = parse(market, selection)
                self.assertEqual((record["PERIOD"], record["PERIOD_SOURCE"]),
                                 ("FULL_TIME", "BETCLIC_PL_REGULAR_TIME_RULE_20260905"))

    def test_undocumented_card_contracts_stay_unknown(self):
        for market, selection in (("Punkty za kartki Powyżej/Poniżej", "Powyżej 25,5"),
                                  ("Dokładna liczba kartek - Węgry", "0 - 1"),
                                  ("Pierwszy zespół który otrzyma kartkę", "Bez Kartek")):
            with self.subTest(market=market):
                self.assertEqual(parse(market, selection)["PERIOD"], "UNKNOWN")

    def test_explicit_half_still_wins(self):
        self.assertEqual(parse("Punkty za kartki Powyżej/Poniżej - 1. połowa", "Powyżej 5,5")["PERIOD"], "1ST_HALF")


if __name__ == "__main__":
    unittest.main()
