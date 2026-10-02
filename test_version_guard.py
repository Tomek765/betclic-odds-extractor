"""Live 2026-10-02 (Wegry - Gruzja): the newest release's test ran the old build EXPAND2.

An older build than one already used on the computer must announce itself
(GUI warning, failing live self-test) instead of quietly bringing old errors
back; an empty optional tab is a visible warning, not a silent PASS and not a
blocked context.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import version_guard
from core import BUILD_ID, BUILD_SEQ, llm_packet
from release_self_test import _verdict
from version_guard import check_build


class VersionGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "NEWEST_BUILD.json"
        self.env = mock.patch.dict(os.environ, {"APEX_VERSION_GUARD_PATH": str(self.path)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_first_run_records_the_build(self):
        self.assertFalse(check_build("FAST3", 202610021630)["outdated"])
        self.assertEqual(json.loads(self.path.read_text())["build_seq"], 202610021630)

    def test_older_build_after_newer_is_outdated_and_does_not_overwrite(self):
        check_build("FAST3", 202610021630)
        result = check_build("EXPAND2", 202609291845)
        self.assertTrue(result["outdated"])
        self.assertEqual(result["newest_build_id"], "FAST3")
        self.assertEqual(json.loads(self.path.read_text())["build_id"], "FAST3")

    def test_newer_build_updates_the_record(self):
        check_build("FAST3", 202610021630)
        self.assertFalse(check_build("FAST4", 202610051200)["outdated"])
        self.assertEqual(json.loads(self.path.read_text())["build_id"], "FAST4")

    def test_damaged_guard_file_never_stops_the_program(self):
        self.path.write_text("{not json", encoding="utf-8")
        result = check_build("FAST3", 202610021630)
        self.assertFalse(result["outdated"])
        self.assertTrue(result["guard_error"].startswith("READ:"))

    def test_no_local_app_data_means_no_guard(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(version_guard.guard_path())
            self.assertFalse(check_build("FAST3", 1)["outdated"])

    def test_current_build_constants(self):
        self.assertTrue(BUILD_ID.endswith("_FAST4"))
        self.assertEqual(len(str(BUILD_SEQ)), 12)


class SelfTestVerdict(unittest.TestCase):
    GOOD = {"odds_count": 800, "context_status": "PASS_WITH_QUARANTINE", "products_distinct": True,
            "products_clean": True, "quarantine_explained": True, "unresolved_count": 0}

    def test_outdated_build_fails_even_with_perfect_products(self):
        verdict = _verdict({**self.GOOD, "extract_status": "GOTOWE", "running_build_outdated": True})
        self.assertEqual(verdict["verdict"], "FAIL")
        self.assertIn("OUTDATED_PROGRAM_VERSION", verdict["structural_incomplete_reasons"])

    def test_empty_optional_tab_is_a_warning(self):
        verdict = _verdict({**self.GOOD, "extract_status": "PARTIAL", "incomplete_reasons": ["EMPTY_MAIN_TAB"]})
        self.assertEqual(verdict["verdict"], "PASS_WITH_WARNINGS")

    def test_structural_gap_still_fails(self):
        verdict = _verdict({**self.GOOD, "extract_status": "PARTIAL", "incomplete_reasons": ["NOT_STABILIZED"]})
        self.assertEqual(verdict["verdict"], "FAIL")


class EmptyTabIsNamedInThePackage(unittest.TestCase):
    def test_data_status_names_the_empty_tab(self):
        text = llm_packet("A - B", "Liga", "20:45", [],
                          {"PARSER_TRUTH_STATUS": "PARTIAL", "ANALYSIS_READY": "NO"}, ["Strzelcy"])
        self.assertIn("DATA_STATUS=PARTIAL EMPTY_TABS=Strzelcy", text)

    def test_kickoff_and_capture_instants_are_written_when_known(self):
        text = llm_packet("A - B", "Liga", "20:45", [], {"PARSER_TRUTH_STATUS": "PASS", "ANALYSIS_READY": "YES"},
                          [], "2026-10-02T18:45:00.000000Z", "2026-10-02T16:10:05.000000Z")
        lines = text.splitlines()
        self.assertEqual(lines[:5], ["MATCH=A - B", "COMPETITION=Liga", "KICKOFF=20:45",
                                     "KICKOFF_UTC=2026-10-02T18:45:00.000000Z",
                                     "CAPTURED_UTC=2026-10-02T16:10:05.000000Z"])
        unknown = llm_packet("A - B", "Liga", "20:45", [], {"PARSER_TRUTH_STATUS": "PASS", "ANALYSIS_READY": "YES"})
        self.assertNotIn("KICKOFF_UTC", unknown)
        self.assertNotIn("CAPTURED_UTC", unknown)

    def test_complete_package_has_no_status_line(self):
        text = llm_packet("A - B", "Liga", "20:45", [],
                          {"PARSER_TRUTH_STATUS": "PASS", "ANALYSIS_READY": "YES"}, [])
        self.assertNotIn("DATA_STATUS", text)


if __name__ == "__main__":
    unittest.main()
