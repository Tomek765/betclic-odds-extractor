"""Numeric player/period labels must never masquerade as scorer goal counts."""
import unittest
from pathlib import Path

from parser import scorer_scope_from_evidence
from replay import replay_real_prematch


class ScorerScopeNumericFirewall(unittest.TestCase):
    def test_second_half_number_is_not_two_goal_scope(self):
        self.assertEqual(
            scorer_scope_from_evidence(
                "Którykolwiek zawodnik strzeli gola - 2. połowa"
            ),
            ("", "COLUMN_SEMANTICS_UNRESOLVED"),
        )

    def test_player_count_is_not_goal_count(self):
        self.assertEqual(
            scorer_scope_from_evidence(
                "Którykolwiek zawodnik strzeli gola - 3 graczy"
            ),
            ("", "COLUMN_SEMANTICS_UNRESOLVED"),
        )

    def test_explicit_goal_counts_remain_proven(self):
        self.assertEqual(
            scorer_scope_from_evidence(
                "Którykolwiek z graczy strzeli 2 gole lub więcej"
            ),
            ("TWO_OR_MORE_GOALS", "PROVEN"),
        )
        self.assertEqual(
            scorer_scope_from_evidence(
                "Którykolwiek z graczy strzeli 3 gole lub więcej"
            ),
            ("THREE_OR_MORE_GOALS", "PROVEN"),
        )

    def test_saved_replay_has_no_period_or_player_count_scope_leak(self):
        report = replay_real_prematch(
            Path("diagnostics/raw_before_dedupe_run_1787475817_15748.jsonl")
        )
        period_rows = [row for row in report["odds"] if row["MARKET"] in {
            "Którykolwiek zawodnik strzeli gola - 2. połowa",
            "Którykolwiek zawodnik strzeli gola (3 pl) - 2. połowa",
        }]
        player_count_rows = [row for row in report["odds"] if row["MARKET"] ==
                             "Którykolwiek zawodnik strzeli gola - 3 graczy"]
        self.assertEqual(len(period_rows), 9)
        self.assertEqual(len(player_count_rows), 3)
        self.assertEqual({row["SCORER_SCOPE"] for row in period_rows + player_count_rows},
                         {"ANYTIME"})


if __name__ == "__main__":
    unittest.main()
