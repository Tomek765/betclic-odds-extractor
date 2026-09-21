"""Real Elche–Barcelona regressions for assist-and-team-result cells."""
import unittest

from core import partition_semantic_records, semantic_quarantine_ledger
from parser import parse_market_record


RUN_ID = "run_1787475817_15748"
PLAYERS = (
    ("Grady Diangana", "22", "29", "13.25"),
    ("Josan Ferrández", "22", "29", "13.25"),
    ("German Valera", "23", "30", "14.25"),
    ("Lamine Yamal", "2.92", "26", "55"),
    ("Raphinha", "2.97", "27", "55"),
    ("Anthony Gordon", "3.53", "33", "65"),
)
CONDITIONS = (
    ("i jego zespół wygra", "ASSIST_AND_TEAM_WIN"),
    ("i jego zespół zremisuje", "ASSIST_AND_TEAM_DRAW"),
    ("i zespół przegra", "ASSIST_AND_TEAM_LOSS"),
)


def real_rows():
    for tab, first_id, section in (("Strzelcy", 710, "Strzelec"),
                                   ("Statystyki", 1597, "Rzuty rożne")):
        for player_index, player_row in enumerate(PLAYERS):
            player, *odds = player_row
            for column_index, (heading, condition) in enumerate(CONDITIONS):
                yield {
                    "source_id": f"{RUN_ID}:{first_id + player_index * 3 + column_index}",
                    "tab": tab, "section": section, "player": player,
                    "odds": odds[column_index], "heading": heading,
                    "condition": condition, "row": player_index + 1,
                    "column": column_index + 1,
                }


REAL_ASSIST_RESULT_ROWS = tuple(real_rows())


def parse_row(raw, *, title="Zawodnik zaliczy asystę", player=None, heading=None):
    player = raw["player"] if player is None else player
    heading = raw["heading"] if heading is None else heading
    instance = (
        f"tab:{raw['tab']}|sports-grouped-markets[assistResult]|"
        f"column:{heading}|row#{raw['row']}|cell#{raw['column']}"
    )
    return parse_market_record(
        category=raw["tab"], market_title=title, raw_selection=player,
        odds_str=raw["odds"], raw_text=f"{player} {raw['odds']}",
        section_title=raw["section"], participant_hint=None, line_hint="",
        period_hint=heading, ancestor_title=raw["section"], main_tab=raw["tab"],
        home_team="Elche", away_team="Barcelona",
        container_id="bounded-assist-result-cell", market_instance_id=instance,
        raw_record_id=raw["source_id"], source_raw_record_ids=[raw["source_id"]],
    )


class PlayerAssistResultCompoundRepair(unittest.TestCase):
    def test_all_36_real_cells_preserve_player_condition_and_odds(self):
        self.assertEqual(len(REAL_ASSIST_RESULT_ROWS), 36)
        for raw in REAL_ASSIST_RESULT_ROWS:
            with self.subTest(source_id=raw["source_id"]):
                row, unresolved = parse_row(raw)
                self.assertIsNone(unresolved)
                self.assertEqual(
                    (row["FAMILY"], row["PARTICIPANT"], row["PARTICIPANTS"],
                     row["OWNER"], row["SELECTION"], row["LINE"], row["PERIOD"],
                     row["PERIOD_SOURCE"], row["PERIOD_CONFIDENCE"],
                     row["SETTLEMENT"], row["ODDS"]),
                    ("PLAYER_PROP", raw["player"], [raw["player"]], "",
                     raw["condition"], "", "FULL_TIME", "BETCLIC_PL_REGULAR_TIME_RULE_20260905", "HIGH",
                     "WIN_LOSE", raw["odds"]),
                )
                self.assertEqual(partition_semantic_records([row]), ([row], []))

    def test_adjacent_rows_and_three_columns_do_not_cross_link(self):
        for start in (0, 18):
            raw_rows = REAL_ASSIST_RESULT_ROWS[start:start + 6]
            parsed = [parse_row(raw)[0] for raw in raw_rows]
            self.assertEqual([row["PARTICIPANT"] for row in parsed],
                             [raw["player"] for raw in raw_rows])
            self.assertEqual([row["SELECTION"] for row in parsed],
                             [raw["condition"] for raw in raw_rows])
            self.assertEqual([row["ODDS"] for row in parsed],
                             [raw["odds"] for raw in raw_rows])
            self.assertEqual(len({row["MARKET_INSTANCE_ID"] for row in parsed}), 6)

    def test_title_and_column_contract_must_both_match(self):
        raw = REAL_ASSIST_RESULT_ROWS[0]
        wrong_title, _ = parse_row(raw, title="Zawodnik zanotuje asystę")
        wrong_column, _ = parse_row(raw, heading="1 +")
        self.assertNotEqual(wrong_title["SELECTION"], "ASSIST_AND_TEAM_WIN")
        self.assertNotEqual(wrong_column["FAMILY"], "PLAYER_PROP")

    def test_empty_bounded_player_never_gains_scope_or_acceptance(self):
        row, _ = parse_row(REAL_ASSIST_RESULT_ROWS[0], player="")
        accepted, quarantined = partition_semantic_records([row])
        self.assertEqual(accepted, [])
        self.assertEqual(quarantined, [row])
        self.assertEqual(row["PARTICIPANT"], "")
        self.assertEqual(
            semantic_quarantine_ledger(quarantined)[0]["reason"],
            "UNCONFIRMED_PLAYER_PROP_SCOPE",
        )


if __name__ == "__main__":
    unittest.main()
