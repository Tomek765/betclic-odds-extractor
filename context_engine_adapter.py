"""Thin, failure-isolated bridge from the extractor GUI to Context Engine V1."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class ContextRunResult:
    status: str
    json_path: Path | None
    text_path: Path | None
    reason: str


@lru_cache(maxsize=4)
def packet_is_ready(packet_text: str) -> bool:
    if not packet_text.strip():
        return False
    try:
        from apex_context_engine.engine import validate_packet
        from apex_context_engine.packet_parser import parse_packet_text

        errors, _ = validate_packet(parse_packet_text(packet_text))
        return not errors
    except Exception:
        # GUI readiness must fail closed and never break the extractor.
        return False


def _value(output: str, prefix: str) -> str | None:
    for line in output.splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return None


def _verified_output(expected: Path, reported: str | None) -> Path | None:
    if expected.is_file():
        return expected
    candidate = Path(reported) if reported else None
    return candidate if candidate and candidate.is_file() else None


def run_context_engine(packet_text: str, module_root: Path, output_dir: Path, timeout_seconds: float = 30.0) -> ContextRunResult:
    if not packet_is_ready(packet_text):
        return ContextRunResult("BLOCKED", None, None, "MISSING_OR_NOT_READY_PACKET")
    frozen = bool(getattr(sys, "frozen", False))
    if not frozen and not (module_root / "apex_context_engine" / "cli.py").is_file():
        return ContextRunResult("BLOCKED", None, None, "CONTEXT_ENGINE_MODULE_NOT_FOUND")
    temp_input: Path | None = None
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False, newline="\n") as handle:
            handle.write(packet_text)
            temp_input = Path(handle.name)
        if frozen:
            from apex_context_engine.engine import build_context
            from apex_context_engine.packet_parser import parse_packet_file
            from apex_context_engine.report import write_outputs

            context = build_context(parse_packet_file(temp_input))
            json_path, text_path = write_outputs(context, output_dir)
            reason = "|".join(context.blocked_reasons)
            missing = [name for name, path in (("JSON", json_path), ("TEXT", text_path)) if not path.is_file()]
            if context.status in {"PASS", "PASS_WITH_QUARANTINE"} and missing:
                return ContextRunResult("BLOCKED", None, None, "CONTEXT_ENGINE_OUTPUT_MISSING:" + ",".join(missing))
            return ContextRunResult(context.status, json_path, text_path, reason)
        completed = subprocess.run(
            [sys.executable, "-m", "apex_context_engine.cli", "--input", str(temp_input), "--output-dir", str(output_dir)],
            cwd=module_root, text=True, encoding="utf-8", errors="replace", capture_output=True,
            timeout=timeout_seconds, check=False,
        )
        status = _value(completed.stdout, "CONTEXT_ENGINE_STATUS=") or "BLOCKED"
        if status not in {"PASS", "PASS_WITH_QUARANTINE", "BLOCKED"}:
            return ContextRunResult("BLOCKED", None, None, f"CONTEXT_ENGINE_STATUS_INVALID:{status}")
        if completed.returncode and status in {"PASS", "PASS_WITH_QUARANTINE"}:
            detail = completed.stderr.strip() or "NO_STDERR"
            return ContextRunResult("BLOCKED", None, None, f"CONTEXT_ENGINE_PROCESS_EXIT:{completed.returncode}:{detail}")
        json_value, text_value = _value(completed.stdout, "JSON="), _value(completed.stdout, "TEXT=")
        reason = _value(completed.stdout, "REASONS=") or completed.stderr.strip()
        expected_json = output_dir / "APEX_CONTEXT_PACKET.json"
        expected_text = output_dir / "APEX_CONTEXT_REPORT.txt"
        json_path = _verified_output(expected_json, json_value)
        text_path = _verified_output(expected_text, text_value)
        if status in {"PASS", "PASS_WITH_QUARANTINE"}:
            missing = [name for name, path in (("JSON", json_path), ("TEXT", text_path)) if path is None]
            if missing:
                return ContextRunResult("BLOCKED", None, None, "CONTEXT_ENGINE_OUTPUT_MISSING:" + ",".join(missing))
        return ContextRunResult(status, json_path, text_path, reason)
    except subprocess.TimeoutExpired:
        return ContextRunResult("BLOCKED", None, None, "CONTEXT_ENGINE_TIMEOUT")
    except OSError as exc:
        return ContextRunResult("BLOCKED", None, None, f"CONTEXT_ENGINE_OS_ERROR:{exc}")
    except Exception as exc:
        return ContextRunResult("BLOCKED", None, None, f"CONTEXT_ENGINE_ERROR:{type(exc).__name__}:{exc}")
    finally:
        if temp_input is not None:
            try:
                temp_input.unlink(missing_ok=True)
            except OSError:
                pass
