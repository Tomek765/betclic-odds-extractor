"""Real Elche–Barcelona regressions for bounded assist-threshold rows."""
import unittest

from core import partition_semantic_records, semantic_quarantine_ledger
from parser import classify_family, parse_market_record


RUN_ID = "run_1787475817_15748"

# The same grouped market is rendered in two tabs.  Every player row has two
# bounded cells whose explicit headings are 1+ and 2+ respectively.
REGULAR_PLAYERS = (
    ("Grady Diangana", "7.00", "50"),
    ("Josan Ferrández", "7.00", "50"),
    ("German Valera", "7.50", "60"),
    ("Lamine Yamal", "2.80", "11"),
    ("Raphinha", "2.85", "12"),
    ("Anthony Gordon", "3.40", "16"),
)

SUPERSUB_PLAYERS = (
    ("German Valera", "6.50", "50"),
    ("Josan Ferrández", "6.50", "40"),
    ("Grady Diangana", "6.50", "40"),
    ("Lamine Yamal", "2.55", "9.50"),
    ("Raphinha", "2.60", "9.50"),
    ("Anthony Gordon", "3.00", "13"),
)


def regular_rows():
    for tab, first_id, section in (("Strzelcy", 698, "Strzelec"),
                                   ("Statystyki", 1585, "Rzuty rożne")):
        for player_index, (player, odds_1, odds_2) in enumerate(REGULAR_PLAYERS):
            for column_index, (hint, odds, line) in enumerate(
                (("1 +", odds_1, "0.5"), ("2 +", odds_2, "1.5"))
            ):
                yield {
                    "source_id": f"{RUN_ID}:{first_id + player_index * 2 + column_index}",
                    "tab": tab,
                    "title": "Zawodnik zanotuje asystę",
                    "section": section,
                    "player": player,
                    "odds": odds,
                    "hint": hint,
                    "line": line,
                    "row": player_index + 1,
                    "column": column_index + 1,
                }


def supersub_rows():
    for player_index, (player, odds_1, odds_2) in enumerate(SUPERSUB_PLAYERS):
        for column_index, (hint, odds, line) in enumerate(
            (("1 asysta lub więcej", odds_1, "0.5"),
             ("2 asysty lub więcej", odds_2, "1.5"))
        ):
            yield {
                "source_id": f"{RUN_ID}:{383 + player_index * 2 + column_index}",
                "tab": "SuperSub",
                "title": "Zawodnik asystujący + jego zmiennik",
                "section": "Strzelec",
                "player": player,
                "odds": odds,
                "hint": hint,
                "line": line,
                "row": player_index + 1,
                "column": column_index + 1,
            }


REAL_ASSIST_THRESHOLD_ROWS = tuple(regular_rows()) + tuple(supersub_rows())


def parse_real_row(raw):
    instance = (
        f"tab:{raw['tab']}|sports-grouped-markets[assistThreshold]|"
        f"column:{raw['hint']}|row#{raw['row']}|cell#{raw['column']}"
    )
    return parse_market_record(
        category=raw["tab"], market_title=raw["title"],
        raw_selection=raw["player"], odds_str=raw["odds"],
        raw_text=f"{raw['player']} {raw['odds']}",
        section_title=raw["section"], participant_hint=None, line_hint="",
        period_hint=raw["hint"], ancestor_title=raw["section"],
        main_tab=raw["tab"], home_team="Elche", away_team="Barcelona",
        container_id="bounded-assist-threshold-cell", market_instance_id=instance,
        raw_record_id=raw["source_id"], source_raw_record_ids=[raw["source_id"]],
    )


class PlayerAssistThresholdRepair(unittest.TestCase):
    def test_all_36_real_cells_preserve_player_threshold_and_odds(self):
        self.assertEqual(len(REAL_ASSIST_THRESHOLD_ROWS), 36)
        for raw in REAL_ASSIST_THRESHOLD_ROWS:
            with self.subTest(source_id=raw["source_id"]):
                row, unresolved = parse_real_row(raw)
                self.assertIsNone(unresolved)
                self.assertEqual(
                    (row["FAMILY"], row["PARTICIPANT"], row["PARTICIPANTS"],
                     row["OWNER"], row["SELECTION"], row["LINE"],
                     row["PERIOD"], row["PERIOD_SOURCE"],
                     row["PERIOD_CONFIDENCE"], row["SETTLEMENT"], row["ODDS"]),
                    ("PLAYER_PROP", raw["player"], [raw["player"]], "", "OVER",
                     raw["line"], "FULL_TIME", "BETCLIC_PL_REGULAR_TIME_RULE_20260905", "HIGH", "WIN_LOSE",
                     raw["odds"]),
                )
                self.assertEqual(partition_semantic_records([row]), ([row], []))

    def test_adjacent_players_columns_and_tabs_do_not_cross_link(self):
        checks = (
            REAL_ASSIST_THRESHOLD_ROWS[0:4],
            REAL_ASSIST_THRESHOLD_ROWS[12:16],
            REAL_ASSIST_THRESHOLD_ROWS[24:28],
        )
        for bounded_rows in checks:
            parsed = [parse_real_row(raw)[0] for raw in bounded_rows]
            self.assertEqual([row["PARTICIPANT"] for row in parsed],
                             [raw["player"] for raw in bounded_rows])
            self.assertEqual([row["LINE"] for row in parsed], ["0.5", "1.5", "0.5", "1.5"])
            self.assertEqual([row["ODDS"] for row in parsed],
                             [raw["odds"] for raw in bounded_rows])
            self.assertEqual(len({row["MARKET_INSTANCE_ID"] for row in parsed}), 4)

    def test_compound_combination_and_xtra_assist_titles_are_firewalled(self):
        other_contracts = (
            ("Zawodnik zaliczy asystę", "i jego zespół wygra"),
            ("Którykolwiek zawodnik zaliczy asystę", "Lamine Yamal / Raphinha"),
            ("Którykolwiek zawodnik zaliczy asystę - 3 zawodników", "A / B / C"),
            ("Zawodnik zaliczy asystę - Xtra Wygrana", "Lamine Yamal"),
        )
        for title, selection in other_contracts:
            with self.subTest(title=title):
                self.assertNotEqual(
                    classify_family(title, selection, "Strzelec", "Elche", "Barcelona")[0],
                    "PLAYER_PROP",
                )


if __name__ == "__main__":
    unittest.main()
