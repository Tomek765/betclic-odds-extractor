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


_JUNK = ("MARKET_INSTANCE_ID", "SOURCE_RAW_RECORD_IDS", "RUNTIME_", "SHA256", "BUILD_ID", "app-desktop[",
         "marketBox_", "record_mappings", "QUARANTINED_RECORDS", "UPSTREAM_EXCLUSIONS", "WARNING_DISPOSITIONS")


def _product_checks(odds_package: str, context_path: Path | None, output_dir: Path) -> dict[str, Any]:
    """Prove the two copied products are different and free of technical data."""
    context_text = context_path.read_text(encoding="utf-8") if context_path and context_path.is_file() else ""
    odds_header = "FAMILY|MARKET|PERIOD|OWNER|SELECTION|LINE|ODDS|SETTLEMENT"
    checks: dict[str, Any] = {
        "odds_package_bytes": len(odds_package.encode("utf-8")),
        "context_bytes": len(context_text.encode("utf-8")),
        "products_distinct": bool(odds_package and context_text and odds_package != context_text
                                  and odds_header in odds_package and odds_header not in context_text
                                  and context_text.startswith("APEX_MATCH_CONTEXT")),
        "products_clean": not any(token in odds_package or token in context_text for token in _JUNK),
    }
    diagnostics_path = output_dir / "APEX_QUARANTINE_DIAGNOSTICS.json"
    if diagnostics_path.is_file():
        rows = json.loads(diagnostics_path.read_text(encoding="utf-8"))
        summary: dict[str, int] = {}
        for row in rows:
            key = f"{row['disposition']}:{row['source_stage']}:{row['reason_code']}"
            summary[key] = summary.get(key, 0) + 1
        checks["quarantine_summary"] = dict(sorted(summary.items()))
        checks["quarantine_explained"] = all(row.get("reason_code") and row.get("source_stage") for row in rows)
    return checks


# Reasons that only describe individual offers the parser could not prove.
# Each such row is quarantined with an explicit reason; the capture itself is
# complete.  Every other incomplete reason is structural and fails the test.
CONTENT_ONLY_INCOMPLETE_REASONS = frozenset({"UNRESOLVED", "PERIOD_UNKNOWN", "PERIOD_LOW_CONFIDENCE"})


def _verdict(report: dict[str, Any]) -> dict[str, Any]:
    """PASS, PASS_WITH_WARNINGS (explained content quarantine only) or FAIL."""
    structural = sorted(set(report.get("incomplete_reasons") or []) - CONTENT_ONLY_INCOMPLETE_REASONS)
    products_ok = (
        int(report.get("odds_count") or 0) > 0
        and report.get("context_status") in {"PASS", "PASS_WITH_QUARANTINE"}
        and report.get("products_distinct") is True
        and report.get("products_clean") is True
    )
    if products_ok and report.get("extract_status") == "GOTOWE" and not int(report.get("unresolved_count") or 0):
        verdict = "PASS"
    elif (products_ok and report.get("extract_status") == "PARTIAL" and not structural
          and report.get("quarantine_explained") is True):
        verdict = "PASS_WITH_WARNINGS"
    else:
        verdict = "FAIL"
    return {"verdict": verdict, "structural_incomplete_reasons": structural,
            "passed": verdict != "FAIL"}


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
            "incomplete_reasons": list(extraction.get("incomplete_reasons") or []),
            "analysis_ready": extraction.get("analysis_ready"),
            "full_usable_ready": extraction.get("full_usable_ready"),
        })
        if packet_text:
            source_packet = output_dir / "APEX_SOURCE_PACKET.txt"
            source_packet.write_text(packet_text, encoding="utf-8", newline="\n")
            # The two user products, exactly as the copy buttons deliver them.
            odds_package = extraction.get("llm_packet_text", "")
            package_path = output_dir / "APEX_ODDS_PACKAGE.txt"
            package_path.write_text(odds_package, encoding="utf-8", newline="\n")
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
                "odds_package": _path(package_path),
                "context_json": _path(context.json_path),
                "context_text": _path(context.text_path),
            })
            report.update(_product_checks(odds_package, context.text_path, output_dir))
        report.update(_verdict(report))
        accepted = report["passed"]
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
