import unittest
from parser import parse_market_record


class TeamFreeKickBinary(unittest.TestCase):
    def test_team_direct_free_kick_is_binary_not_goal_total(self):
        row, issue = parse_market_record(category="Gole", market_title="Strzelą gola bezpośrednio z rzutu wolnego - Sunderland",
            raw_selection="Tak", odds_str="14.75", raw_text="Tak 14.75", section_title="Gole - popularne",
            home_team="Sunderland", away_team="Hull", container_id="source", raw_record_id="run_1788889152_14972:1015")
        self.assertIsNone(issue)
        self.assertEqual((row["FAMILY"], row["OWNER"], row["SETTLEMENT"]), ("BINARY_EVENT", "Sunderland", "WIN_LOSE"))
        self.assertEqual((row["RAW"], row["ODDS"]), ("Tak 14.75", "14.75"))
