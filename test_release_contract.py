import sys
from pathlib import Path

from context_engine_adapter import run_context_engine
from apex_context_engine.cli import main as context_cli_main
from core import dismiss_known_betclic_overlays, find_chrome_exe
from diagnostics import get_data_dir


ROOT = Path(__file__).resolve().parent
FIXTURE = ROOT / "tests_context" / "fixtures" / "minimal_packet.txt"


def test_frozen_data_dir_uses_explicit_isolated_override(tmp_path, monkeypatch):
    isolated = tmp_path / "dane użytkownika"
    monkeypatch.setenv("APEX_DATA_DIR", str(isolated))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert get_data_dir() == isolated.resolve()


def test_frozen_runtime_prefers_bundled_chromium(tmp_path, monkeypatch):
    executable = tmp_path / "browser" / "chrome-win" / "chrome.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"contract")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert find_chrome_exe() == str(executable)


def test_frozen_context_engine_runs_in_process(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    result = run_context_engine(
        FIXTURE.read_text(encoding="utf-8"),
        ROOT,
        tmp_path / "wynik",
    )
    assert result.status in {"PASS", "PASS_WITH_QUARANTINE"}
    assert result.json_path and result.json_path.is_file()
    assert result.text_path and result.text_path.is_file()


def test_context_cli_treats_positive_quarantine_status_as_success(tmp_path):
    output = tmp_path / "cli_output"
    exit_code = context_cli_main([
        "--input", str(FIXTURE),
        "--output-dir", str(output),
    ])
    assert exit_code == 0
    assert (output / "APEX_CONTEXT_PACKET.json").is_file()
    assert (output / "APEX_CONTEXT_REPORT.txt").is_file()


def test_known_betclic_promotional_overlay_is_dismissed():
    class Button:
        clicked = False

        def is_visible(self):
            return True

        def click(self, timeout):
            assert timeout == 3000
            self.clicked = True

    class Page:
        button = Button()

        def query_selector(self, selector):
            if selector.startswith("sports-extra-win-onboarding-modal"):
                return self.button
            return None

    page = Page()
    messages = []
    assert dismiss_known_betclic_overlays(page, messages.append) == 1
    assert page.button.clicked is True
    assert messages and messages[0].startswith("BETCLIC_MODAL_DISMISSED")
