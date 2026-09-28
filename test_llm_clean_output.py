"""Regression: the user/LLM output carries bets only, never scraper metadata.

The extraction result keeps two texts: ``packet_text`` is the internal machine
packet for the Context Engine (lineage ids, accounting, diagnostics) and
``llm_packet_text`` is what the preview shows and the copy button copies.
These tests pin the clean text against a real 1236-row capture processed by
the production canonical export boundary.
"""
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import replay
from apex_context_engine.engine import build_context
from apex_context_engine.llm_format import COLUMNS, odds_row, parse_llm_row, render_llm_odds
from apex_context_engine.packet_parser import parse_packet_text
from apex_context_engine.report import write_outputs
from core import canonical_export_boundary, llm_packet

ROOT = Path(__file__).parent
CAPTURE = ROOT / "tests_context/fixtures/kaiserslautern_darmstadt/raw_before_dedupe_run_1788588979_12912.jsonl"
FORBIDDEN = (
    "MARKET_INSTANCE_ID", "SOURCE_RAW_RECORD_IDS", "SOURCE_RECORD_ID", "RUNTIME_", "CORE_PATH",
    "SHA256", "RUN_ID", "RAW_FILE", "app-desktop[", "sports-match-page", "marketBox_",
    "record_mappings", "QUARANTINED_RECORDS", "UPSTREAM_EXCLUSIONS", "WARNING_DISPOSITIONS",
    "BUILD_ID", "DOM_PATH", "PERIOD_SOURCE", "EQUIVALENCE_GROUP", "SEMANTIC_QUARANTINE", "[TAB_TRUTH]",
)
READY = {"PARSER_TRUTH_STATUS": "PASS", "ANALYSIS_READY": "YES"}


def _norm(value):
    return " ".join(str("" if value is None else value).split())


def setUpModule():
    global ACCEPTED, CLEAN, HOME, AWAY
    parsed = []
    original = replay.parse_market_record

    def collect(**kwargs):
        row, issue = original(**kwargs)
        if row:
            parsed.append(row)
        return row, issue

    with patch.object(replay, "parse_market_record", side_effect=collect):
        replay.replay_real_prematch(CAPTURE)
    HOME, AWAY = replay._capture_teams(replay.load_real_prematch_fixture(CAPTURE))
    _, ACCEPTED, _, _, _ = canonical_export_boundary(parsed, HOME, AWAY)
    CLEAN = llm_packet(f"{HOME} - {AWAY}", "Niemcy Bundesliga 2", "13:00", ACCEPTED, READY)


def _rows(text):
    lines = text.splitlines()
    return lines[lines.index("|".join(COLUMNS)) + 1:]


class CleanLlmOutput(unittest.TestCase):
    def test_1_integrity_every_accepted_bet_has_a_clean_row(self):
        self.assertGreater(len(ACCEPTED), 900)
        rows = set(_rows(CLEAN))
        for record in ACCEPTED:
            row = odds_row(record)
            self.assertTrue(row in rows or any(r.startswith(row + "|RAW=") for r in rows), row)

    def test_2_and_3_odds_and_semantics_are_exact(self):
        semantic = ("FAMILY", "MARKET", "PERIOD", "OWNER", "SELECTION", "LINE", "SETTLEMENT",
                    "HANDICAP_KIND", "HANDICAP_TAXONOMY", "PARTICIPANT", "SCORER_SCOPE")
        for record in ACCEPTED:
            parsed = parse_llm_row(odds_row(record))
            self.assertEqual(parsed["ODDS"], record["ODDS"])
            for key in semantic:
                self.assertEqual(parsed.get(key, ""), _norm(record.get(key)), (key, record["RAW"]))
            names = [_norm(name) for name in record.get("PARTICIPANTS") or []]
            if names and names != [_norm(record.get("PARTICIPANT"))]:
                self.assertEqual(parsed["PARTICIPANTS"].split(" + "), names)

    def test_3b_distinct_player_combinations_stay_distinct(self):
        combos = {tuple(r["PARTICIPANTS"]) for r in ACCEPTED if r["FAMILY"] == "PLAYER_COMBINATION"}
        emitted = {r for r in _rows(CLEAN) if r.startswith("PLAYER_COMBINATION|")}
        self.assertGreaterEqual(len(emitted), len({(r["MARKET"], r["ODDS"], tuple(r["PARTICIPANTS"]))
                                                   for r in ACCEPTED if r["FAMILY"] == "PLAYER_COMBINATION"}))
        self.assertGreater(len(combos), 10)

    def test_3c_only_identical_offers_are_merged(self):
        by_row = {}
        for record in ACCEPTED:
            by_row.setdefault(odds_row(record), set()).add(_norm(record["RAW"]))
        merged = {row for row, raws in by_row.items() if len(raws) == 1}
        rows = _rows(CLEAN)
        self.assertEqual(len(rows), len(merged) + sum(len(r) for row, r in by_row.items() if len(r) > 1))
        self.assertEqual(len(rows), len(set(rows)))

    def test_4_zero_technical_junk(self):
        for token in FORBIDDEN:
            self.assertNotIn(token, CLEAN)
        self.assertIsNone(re.search(r"[A-Za-z]:\\\\|\\.exe\b|run_\d+_\d+:\d+", CLEAN))
        for row in _rows(CLEAN):
            self.assertFalse(re.search(r"\|[A-Z_]+=\|", row + "|"), row)  # no empty optional fields

    def test_5_size_is_bounded_by_bets_not_metadata(self):
        size = len(CLEAN.encode("utf-8"))
        self.assertLess(size / len(ACCEPTED), 150)
        self.assertLess(size, 250_000)

    def test_6_generality_across_market_families(self):
        families = {row.split("|", 1)[0] for row in _rows(CLEAN)}
        for family in ("1X2", "GOALS_OU", "TEAM_TOTALS_HOME", "TEAM_TOTALS_AWAY", "HANDICAP_EUROPEAN",
                       "BTTS", "CORRECT_SCORE", "GOALSCORER", "PLAYER_PROP", "PLAYER_COMBINATION"):
            self.assertIn(family, families)
        header = CLEAN.splitlines()[:5]
        self.assertEqual(header[:3], [f"MATCH={HOME} - {AWAY}", "COMPETITION=Niemcy Bundesliga 2", "KICKOFF=13:00"])

    def test_partial_capture_is_labelled_without_diagnostics(self):
        text = llm_packet("A - B", "L", "20:00", ACCEPTED[:3], {"PARSER_TRUTH_STATUS": "PARTIAL"})
        self.assertIn("DATA_STATUS=PARTIAL", text)
        self.assertNotIn("DATA_STATUS", CLEAN)

    def test_escaping_round_trips(self):
        record = {"FAMILY": "X", "MARKET": "A|B \\ C", "PERIOD": "FULL_TIME", "SELECTION": "S",
                  "ODDS": "2.10", "SETTLEMENT": "WIN_LOSE", "PARTICIPANT": "P|Q"}
        parsed = parse_llm_row(odds_row(record))
        self.assertEqual((parsed["MARKET"], parsed["PARTICIPANT"], parsed["ODDS"]), ("A|B \\ C", "P|Q", "2.10"))
        text = render_llm_odds({"MATCH": "A - B"}, [record, dict(record)])
        self.assertEqual(len(_rows(text)), 1)


class CleanContextReport(unittest.TestCase):
    def test_context_report_is_clean_market_context_and_audit_is_internal(self):
        from tests_context.capture_repair_support import capture_packet
        internal, _, _ = capture_packet(CAPTURE)
        context = build_context(parse_packet_text(internal))
        with tempfile.TemporaryDirectory() as tmp:
            json_path, text_path = write_outputs(context, tmp)
            report = text_path.read_text(encoding="utf-8")
            audit = (Path(tmp) / "APEX_CONTEXT_AUDIT.txt").read_text(encoding="utf-8")
        self.assertEqual(text_path.name, "APEX_CONTEXT_REPORT.txt")
        self.assertIn("QUARANTINED_RECORDS", audit)
        for token in FORBIDDEN + ("INPUT_SHA256", "record_mappings", "source_raw_record_ids"):
            self.assertNotIn(token, report)
        self.assertTrue(report.startswith("APEX_MATCH_CONTEXT\n"))
        self.assertIn("[MARKET_SCRIPT]", report)
        self.assertNotIn("|".join(COLUMNS), report)  # the odds table belongs to the package


class CopyButtonUsesCleanOutput(unittest.TestCase):
    def test_7_clipboard_holds_clean_packet_and_context_gets_internal(self):
        import tkinter as tk
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display")
        root.withdraw()
        import gui
        try:
            app = gui.BetclicExtractorGUI(root)
            internal = 'BETCLIC_FULL_ODDS_PACKET{\nMARKET_INSTANCE_ID="tab:Top|app-desktop[#3]";\n}'
            with patch.object(gui.messagebox, "showinfo"), patch.object(gui, "packet_is_ready", return_value=True):
                app._on_done({"status": "GOTOWE", "packet_text": internal, "llm_packet_text": CLEAN,
                              "odds_count": len(ACCEPTED)})
                app.btn_copy.invoke()
            self.assertEqual(root.clipboard_get().strip(), CLEAN.strip())
            self.assertEqual(app.current_packet, internal)
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
