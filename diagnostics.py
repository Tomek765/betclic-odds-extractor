from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any


def get_app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def get_data_dir() -> Path:
    """Return the writable application-data root.

    Development keeps artifacts beside the source for easy inspection.  A
    frozen portable or installed build always writes to the user's local app
    data, never into the read-only release/installation directory.
    """
    override = os.environ.get("APEX_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        local_app_data = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if local_app_data:
            return Path(local_app_data) / "APEX Context Engine"
        return Path.home() / "AppData" / "Local" / "APEX Context Engine"
    return get_app_dir()


def get_profile_dir() -> Path:
    """
    Browser profile is stored OUTSIDE the EXE / dist tree so it is never
    locked during a rebuild.  When frozen we use %APPDATA%; during dev we
    use a sibling folder of the script.
    """
    profile = get_data_dir() / "browser_profile"
    profile.mkdir(parents=True, exist_ok=True)
    return profile


BASE_DIR = get_data_dir()
DIAGNOSTICS_DIR = BASE_DIR / "diagnostics"
LOGS_DIR = BASE_DIR / "logs"
SNAPSHOTS_DIR = BASE_DIR / "snapshots"
PROFILE_DIR = get_profile_dir()

for d in [DIAGNOSTICS_DIR, LOGS_DIR, SNAPSHOTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)


class DiagnosticsManager:
    def __init__(self, timestamp: int | None = None) -> None:
        self.ts = timestamp or int(time.time())
        self.log_file = LOGS_DIR / f"extractor_{self.ts}.log"

    def log(self, message: str) -> None:
        formatted = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n"
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(formatted)
                f.flush()
        except Exception:
            pass

    def save_raw_html(self, html_content: str) -> Path:
        filepath = SNAPSHOTS_DIR / f"snapshot_{self.ts}.html"
        filepath.write_text(html_content, encoding="utf-8")
        self.log(f"Saved raw HTML snapshot: {filepath}")
        return filepath

    def save_dom_json(self, dom_data: dict[str, Any]) -> Path:
        filepath = DIAGNOSTICS_DIR / f"dom_{self.ts}.json"
        filepath.write_text(json.dumps(dom_data, ensure_ascii=False, indent=2), encoding="utf-8")
        self.log(f"Saved DOM JSON snapshot: {filepath}")
        return filepath

    def save_expansion_log(self, expansion_entries: list[dict[str, Any]]) -> Path:
        filepath = DIAGNOSTICS_DIR / f"expansion_{self.ts}.json"
        filepath.write_text(json.dumps(expansion_entries, ensure_ascii=False, indent=2), encoding="utf-8")
        self.log(f"Saved expansion log: {filepath}")
        return filepath

    def save_unresolved_log(self, unresolved_items: list[dict[str, Any]]) -> Path:
        filepath = DIAGNOSTICS_DIR / f"unresolved_{self.ts}.json"
        filepath.write_text(json.dumps(unresolved_items, ensure_ascii=False, indent=2), encoding="utf-8")
        self.log(f"Saved unresolved log: {filepath}")
        return filepath

    def save_screenshot(self, page_or_bytes: Any) -> Path:
        filepath = DIAGNOSTICS_DIR / f"screenshot_{self.ts}.png"
        try:
            if hasattr(page_or_bytes, "screenshot"):
                page_or_bytes.screenshot(path=str(filepath), full_page=True)
            elif isinstance(page_or_bytes, bytes):
                filepath.write_bytes(page_or_bytes)
            self.log(f"Saved screenshot: {filepath}")
        except Exception as e:
            self.log(f"Failed to save screenshot: {e}")
        return filepath

    @staticmethod
    def open_diagnostics_folder() -> None:
        os.startfile(str(DIAGNOSTICS_DIR))
