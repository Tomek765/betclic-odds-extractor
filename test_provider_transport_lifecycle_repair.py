import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


class ProviderTransportLifecycleRepairTests(unittest.TestCase):
    def test_success_path_drains_before_browser_close_and_flushes_afterward(self):
        from core import BetclicOddsExtractor

        events = []

        class Listener:
            errors = []
            last_flush_summary = {}

            def drain(self, page, timeout_ms):
                events.append("drain")
                self.assert_page = page
                self.timeout_ms = timeout_ms
                return 0

            def flush(self, directory, bridge):
                events.append("flush")
                self.last_flush_summary = {"ACCEPTED_FOR_PERSISTENCE": 0}
                return []

        listener = Listener()
        mock_header = MagicMock()
        mock_header.inner_text.return_value = "Team A - Team B"
        mock_header.is_visible.return_value = False

        mock_tab = MagicMock()
        mock_tab.inner_text.return_value = "GŁÓWNE"
        mock_tab.query_selector.return_value = None
        mock_tab.get_attribute.return_value = "tab_item isActive"
        mock_tab.is_visible.return_value = False

        mock_page = MagicMock()
        mock_page.goto.return_value = MagicMock(status=200)
        mock_page.title.return_value = "Obstawianie Team A - Team B | Betclic"
        mock_page.query_selector.side_effect = (
            lambda selector: mock_header if ("h1" in selector or "header" in selector) else None
        )
        mock_page.query_selector_all.side_effect = (
            lambda selector: [mock_tab] if ("tab" in selector or "category" in selector) else []
        )
        mock_page.content.return_value = "<html><body></body></html>"

        def mock_eval(script, *args):
            source = str(script)
            if "NO_EVENT_HEADER" in source:
                return {"status": "PREMATCH", "proof": "mock-event-header"}
            if "innerHeight" in source:
                return 800
            if "scrollHeight" in source:
                return 1000
            if "currentTabName" in source or args:
                return [{
                    "container_id": "box_1",
                    "category": "Top",
                    "market": "Suma goli 2.5",
                    "selection": "Powyżej 2.5",
                    "section_title": "",
                    "odds": "1.85",
                    "raw": "Powyżej 2.5 1.85",
                    "missing_header": False,
                    "source_index": 1,
                }]
            if "interactive" in source or "seenButtons" in source:
                return {
                    "interactive_control_count": 1,
                    "priced_candidate_count": 1,
                    "unpriced_control_count": 0,
                    "selectable_count": 1,
                    "remaining_closed": 0,
                    "remaining_more": 0,
                }
            return None

        mock_page.evaluate.side_effect = mock_eval
        mock_context = MagicMock()
        mock_context.pages = [mock_page]
        mock_context.close.side_effect = lambda: events.append("close")
        mock_pw = MagicMock()
        mock_pw.chromium.launch_persistent_context.return_value = mock_context
        mock_pw_cm = MagicMock()
        mock_pw_cm.__enter__.return_value = mock_pw
        mock_pw_cm.__exit__.side_effect = lambda *args: events.append("playwright_exit")
        diagnostics = MagicMock()

        capture_status = {
            "provider_event_id": "123",
            "kickoff_at": "2030-01-01T12:00:00.000000Z",
            "provider_is_live": False,
            "capture_status": "PREMATCH_VALID",
            "embedded_match_id": "123",
            "exact_match": True,
        }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "logs").mkdir()
            extractor = BetclicOddsExtractor(diag=diagnostics)
            with patch("playwright.sync_api.sync_playwright", return_value=mock_pw_cm), \
                 patch("core.find_chrome_exe", return_value=None), \
                 patch("core.PassiveBetclicTransportListener", return_value=listener), \
                 patch("core.evaluate_capture_status", return_value=capture_status), \
                 patch("core.build_provider_derived_bridge", return_value={"bridge_sha256": "bridge"}), \
                 patch("core.write_history_sidecars", return_value={
                     "run_sidecar_path": str(root / "run.json"),
                     "observations_sidecar_path": str(root / "observations.jsonl"),
                 }), \
                 patch("core.write_bridge_append_only", return_value=root / "bridge.json"), \
                 patch("core.build_and_write_manifest", return_value=root / "manifest.json"), \
                 patch("core.LOGS_DIR", root / "logs"), \
                 patch("core.time.sleep", return_value=None):
                result = extractor.extract(
                    "https://www.betclic.pl/pilka-nozna-sfootball/test-c1/match-m123"
                )

        self.assertEqual(result.get("status"), "GOTOWE")
        self.assertEqual(events.count("drain"), 1)
        self.assertLess(events.index("drain"), events.index("close"))
        self.assertLess(events.index("close"), events.index("flush"))


if __name__ == "__main__":
    unittest.main()
