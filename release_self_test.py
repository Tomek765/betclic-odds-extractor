"""End-to-end release validation entry point used by source and frozen builds."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

from context_engine_adapter import run_context_engine
from core import BetclicOddsExtractor, find_chrome_exe
from diagnostics import BASE_DIR, DiagnosticsManager


def _path(value: Path | None) -> str | None:
    return str(value.resolve()) if value is not None else None


def run_release_e2e(url: str) -> int:
    output_dir = BASE_DIR / "release_self_test"
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / "SELF_TEST_RESULT.json"
    started = time.time()
    browser_executable = find_chrome_exe()
    report: dict[str, Any] = {
        "schema": "APEX_RELEASE_SELF_TEST_V1",
        "source_url": url,
        "frozen": bool(getattr(sys, "frozen", False)),
        "runtime_executable": str(Path(sys.executable).resolve()),
        "runtime_data_root": str(BASE_DIR.resolve()),
        "browser_executable": browser_executable,
        "extract_status": "NOT_RUN",
        "context_status": "NOT_RUN",
        "passed": False,
    }
    exit_code = 10
    try:
        extraction = BetclicOddsExtractor(
            progress_callback=lambda progress, message: print(
                f"PROGRESS={progress:.2f}:{message}", flush=True
            ),
            diag=DiagnosticsManager(),
        ).extract(url)
        packet_text = extraction.get("packet_text", "")
        report.update({
            "extract_status": extraction.get("status"),
            "error_code": extraction.get("error_code", ""),
            "error": extraction.get("error", ""),
            "odds_count": extraction.get("odds_count", 0),
            "market_count": extraction.get("market_count", 0),
            "unresolved_count": extraction.get("unresolved_count", 0),
            "analysis_ready": extraction.get("analysis_ready"),
            "full_usable_ready": extraction.get("full_usable_ready"),
        })
        if packet_text:
            source_packet = output_dir / "APEX_SOURCE_PACKET.txt"
            source_packet.write_text(packet_text, encoding="utf-8", newline="\n")
            context = run_context_engine(
                packet_text,
                Path(__file__).resolve().parent,
                output_dir,
                timeout_seconds=60.0,
            )
            report.update({
                "context_status": context.status,
                "context_reason": context.reason,
                "source_packet": _path(source_packet),
                "context_json": _path(context.json_path),
                "context_text": _path(context.text_path),
            })
        accepted = (
            report["extract_status"] == "GOTOWE"
            and int(report.get("odds_count") or 0) > 0
            and int(report.get("unresolved_count") or 0) == 0
            and report["context_status"] in {"PASS", "PASS_WITH_QUARANTINE"}
        )
        report["passed"] = accepted
        exit_code = 0 if accepted else 20
    except BaseException as exc:
        report["fatal_error"] = f"{type(exc).__name__}:{exc}"
        exit_code = 30
    finally:
        report["duration_seconds"] = round(time.time() - started, 3)
        report["exit_code"] = exit_code
        result_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(run_release_e2e(sys.argv[1] if len(sys.argv) > 1 else ""))
