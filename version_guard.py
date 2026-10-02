"""Never let an older build run unnoticed after a newer one was used.

Live 2026-10-02 (Wegry - Gruzja): the test of the newest release actually ran
the 3-day-old build EXPAND2.  Every release extracted to the same folder name
and the installer replaced a newer program with an older one without a word,
so the user saw errors that had already been fixed.

Every build records the newest build sequence it has seen on this computer
(%LOCALAPPDATA%\\APEX Context Engine\\NEWEST_BUILD.json).  A build that starts
after a newer one was used reports itself as outdated; the GUI warns and the
live self-test fails.  The file lives beside the runtime data but ignores
APEX_DATA_DIR, so isolated live tests still see the real history.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

GUARD_FILE = "NEWEST_BUILD.json"


def guard_path() -> Path | None:
    override = os.environ.get("APEX_VERSION_GUARD_PATH")
    if override:
        return Path(override)
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return None
    return Path(local_app_data) / "APEX Context Engine" / GUARD_FILE


def check_build(build_id: str, build_seq: int, record: bool = True) -> dict[str, Any]:
    """Compare this build with the newest one seen; never raises."""
    path = guard_path()
    result: dict[str, Any] = {
        "build_id": build_id, "build_seq": int(build_seq),
        "newest_build_id": build_id, "newest_build_seq": int(build_seq),
        "outdated": False, "guard_path": str(path or ""), "guard_error": "",
    }
    if path is None:
        return result
    newest_id, newest_seq = "", 0
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            newest_id, newest_seq = str(data.get("build_id") or ""), int(data.get("build_seq") or 0)
    except Exception as exc:  # a damaged file must not stop the program
        result["guard_error"] = f"READ:{type(exc).__name__}"
    if newest_seq > int(build_seq):
        result.update(newest_build_id=newest_id, newest_build_seq=newest_seq, outdated=True)
    elif record and newest_seq < int(build_seq):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"build_id": build_id, "build_seq": int(build_seq)}), encoding="utf-8")
        except Exception as exc:
            result["guard_error"] = f"WRITE:{type(exc).__name__}"
    return result


def outdated_message(check: dict[str, Any]) -> str:
    """User-facing Polish warning for an outdated build (ASCII-safe for consoles)."""
    return (f"UWAGA: uruchomiona jest STARSZA wersja programu ({check.get('build_id')}). "
            f"Na tym komputerze byla juz uzywana nowsza: {check.get('newest_build_id')}. "
            "Zainstaluj ponownie najnowsza paczke (INSTALUJ.cmd).")
