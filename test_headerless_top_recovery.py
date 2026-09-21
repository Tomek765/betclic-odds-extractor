"""Exact recovery contracts for three self-describing Top good-deal rows."""
import unittest
from pathlib import Path

from core import partition_semantic_records, semantic_quarantine_ledger
from parser import parse_market_record, recover_headerless_top_offer
from replay import replay_real_prematch


INSTANCE = (
    "tab:Top|sports-markets-single-market[block.marketElement#0]|"
    "div[marketBox.is-goodDeals#0]|sports-matrix-markets[#1]|row#{}"
)

REAL_ROWS = (
    ("run_1787475817_15748:8", "Czas 1. gola w meczu: 00:00 - 14:59", "2.28", 0),
    ("run_1787475817_15748:9", "Dokładny wynik w grupie: 0-1, 0-2, 0-3", "3.18", 1),
    ("run_1787475817_15748:10", "Anthony Gordon zanotuje asystę", "3.40", 2),
)


def recover_and_parse(raw):
    source_id, source_selection, odds, row_index = raw
    instance = INSTANCE.format(row_index)
    recovered = recover_headerless_top_offer(source_selection, "Top", instance)
    if recovered is None:
        return None, None, None
    row, issue = parse_market_record(
        category="Top", market_title=recovered["market_title"],
        raw_selection=recovered["raw_selection"], odds_str=odds,
        raw_text=f"{source_selection} {odds}", section_title="",
        participant_hint=recovered.get("participant_hint"), line_hint="",
        period_hint="", ancestor_title="", main_tab="Top",
        home_team="Elche", away_team="Barcelona",
        container_id="headerless-good-deal-row", market_instance_id=instance,
        raw_record_id=source_id, source_raw_record_ids=[source_id],
    )
    return recovered, row, issue


class HeaderlessTopRecovery(unittest.TestCase):
    def test_first_goal_time_row_recovers_complete_binary_market(self):
        recovered, row, issue = recover_and_parse(REAL_ROWS[0])
        self.assertIsNone(issue)
        self.assertEqual(
            recovered,
            {"market_title": "Czas 1. gola w meczu", "raw_selection": "00:00 - 14:59"},
        )
        self.assertEqual(
            (row["FAMILY"], row["MARKET"], row["SELECTION"], row["PERIOD"],
             row["PERIOD_SOURCE"], row["SETTLEMENT"], row["ODDS"]),
            ("FIRST_GOAL_TIME", "Czas 1. gola w meczu", "00:00 - 14:59",
             "FULL_TIME", "MARKET_TITLE", "WIN_LOSE", "2.28"),
        )
        self.assertEqual(partition_semantic_records([row]), ([row], []))

    def test_correct_score_group_never_masquerades_as_one_exact_score(self):
        recovered, row, issue = recover_and_parse(REAL_ROWS[1])
        self.assertIsNone(issue)
        self.assertEqual(
            recovered,
            {"market_title": "Dokładny wynik w grupie", "raw_selection": "0-1, 0-2, 0-3"},
        )
        self.assertEqual(
            (row["FAMILY"], row["SELECTION"], row["PERIOD"], row["PERIOD_SOURCE"],
             row["SETTLEMENT"], row["ODDS"]),
            ("CORRECT_SCORE_GROUP", "0-1, 0-2, 0-3", "FULL_TIME",
             "CANONICAL_MARKET", "WIN_LOSE", "3.18"),
        )
        self.assertEqual(partition_semantic_records([row]), ([row], []))

    def test_inline_assist_row_recovers_player_and_regulatory_period(self):
        recovered, row, issue = recover_and_parse(REAL_ROWS[2])
        self.assertIsNone(issue)
        self.assertEqual(
            recovered,
            {"market_title": "Zawodnik zanotuje asystę", "raw_selection": "Over 0.5",
             "participant_hint": "Anthony Gordon"},
        )
        self.assertEqual(
            (row["FAMILY"], row["PARTICIPANT"], row["PARTICIPANTS"], row["SELECTION"],
             row["LINE"], row["PERIOD"], row["SETTLEMENT"], row["ODDS"]),
            ("PLAYER_PROP", "Anthony Gordon", ["Anthony Gordon"], "OVER", "0.5",
             "FULL_TIME", "WIN_LOSE", "3.40"),
        )
        self.assertEqual(partition_semantic_records([row]), ([row], []))

    def test_recovery_requires_top_good_deal_matrix_and_exact_grammar(self):
        self.assertIsNone(recover_headerless_top_offer(REAL_ROWS[0][1], "Strzelcy", INSTANCE.format(0)))
        self.assertIsNone(recover_headerless_top_offer(REAL_ROWS[0][1], "Top", "tab:Top|ordinary-market"))
        self.assertIsNone(recover_headerless_top_offer("Dowolny tekst", "Top", INSTANCE.format(3)))
        self.assertIsNone(recover_headerless_top_offer("Anthony zanotuje asystę", "Top", INSTANCE.format(3)))

    def test_full_saved_replay_accounts_all_three_in_terminal_semantic_states(self):
        report = replay_real_prematch(
            Path("diagnostics/raw_before_dedupe_run_1787475817_15748.jsonl")
        )
        production = report["production_accounting"]
        self.assertEqual(report["unresolved_count"], 0)
        self.assertEqual(production["CANONICAL_ODDS_COUNT"], 1394)
        self.assertEqual(
            production["SEMANTIC_ACCEPTED_COUNT"] + production["SEMANTIC_QUARANTINED_COUNT"],
            1394,
        )
        self.assertEqual(production["UNACCOUNTED_SOURCE_RECORD_COUNT"], 0)
        self.assertTrue(production["ALL_SOURCE_IDS_PRESERVED"])


if __name__ == "__main__":
    unittest.main()
