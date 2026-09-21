"""Append-only history sidecar primitives for APEX History Collection Contract V0.1."""
from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


SCHEMA_VERSION = "APEX_HISTORY_COLLECTION_CONTRACT_V0_1"
PROVIDER = "BETCLIC"
_ROUTE_ID_RE = re.compile(r"-m(\d+)(?=$|[/?#])")
_MATCH_ID_RE = re.compile(r'"matchId"\s*:\s*"(\d+)"')
_MATCH_DATE_RE = re.compile(r'"matchDateUtc"\s*:\s*"([^"\\]+)"')
_IS_LIVE_RE = re.compile(r'"isLive"\s*:\s*(true|false)', re.IGNORECASE)


def utc_now_rfc3339() -> str:
    """Return a timezone-aware UTC wall-clock timestamp with microseconds."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def canonicalize_utc_datetime(value: str | None) -> str | None:
    """Return an RFC3339 UTC value or None when a timestamp is not explicit."""
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_betclic_route_event_id(url: str | None) -> str | None:
    """Extract one exact Betclic event route ID; malformed routes fail closed."""
    if not url or not isinstance(url, str):
        return None
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host not in {"www.betclic.pl", "m.betclic.pl"}:
        return None
    matches = _ROUTE_ID_RE.findall(parsed.path)
    return matches[0] if len(matches) == 1 else None


def extract_embedded_provider_match_info(html: str | None) -> dict[str, Any]:
    """Read only the confirmed Betclic hydration fields, rejecting ambiguity."""
    text = html if isinstance(html, str) else ""
    match_ids = set(_MATCH_ID_RE.findall(text))
    dates = set(_MATCH_DATE_RE.findall(text))
    live_values = {value.lower() == "true" for value in _IS_LIVE_RE.findall(text)}
    return {
        "provider_match_id": next(iter(match_ids)) if len(match_ids) == 1 else None,
        "match_date_utc": next(iter(dates)) if len(dates) == 1 else None,
        "is_live": next(iter(live_values)) if len(live_values) == 1 else None,
    }


def evaluate_capture_status(
    route_event_id: str | None,
    embedded: dict[str, Any],
    preflight_status: str | None,
    capture_started_at: str | None,
    capture_finished_at: str | None = None,
) -> dict[str, Any]:
    """Evaluate the V0.1 prematch gate without modifying legacy capture behavior."""
    embedded_id = embedded.get("provider_match_id")
    kickoff_at = canonicalize_utc_datetime(embedded.get("match_date_utc"))
    provider_is_live = embedded.get("is_live")
    result = {
        "route_event_id": route_event_id,
        "embedded_match_id": embedded_id,
        "exact_match": bool(route_event_id and embedded_id and route_event_id == embedded_id),
        "provider_event_id": route_event_id if route_event_id and route_event_id == embedded_id else None,
        "kickoff_at": kickoff_at,
        "provider_is_live": provider_is_live,
        "preflight_status": (preflight_status or "UNKNOWN").upper(),
        "capture_status": "CAPTURE_FAILED",
        "status_reason": "",
    }
    if not route_event_id or not embedded_id or route_event_id != embedded_id:
        result.update(capture_status="IDENTITY_UNSAFE", status_reason="ROUTE_EVENT_ID_EMBEDDED_MATCH_ID_MISMATCH")
        return result
    if not kickoff_at:
        result.update(capture_status="TIME_UNSAFE", status_reason="KICKOFF_DATETIME_MISSING_OR_AMBIGUOUS")
        return result
    if provider_is_live is not False:
        result.update(
            capture_status="LIVE_REJECTED" if provider_is_live is True else "STATUS_UNSAFE",
            status_reason="PROVIDER_IS_LIVE" if provider_is_live is True else "PROVIDER_IS_LIVE_MISSING",
        )
        return result
    if result["preflight_status"] != "PREMATCH":
        result.update(capture_status="STATUS_UNSAFE", status_reason="PREFLIGHT_NOT_PREMATCH")
        return result
    started_at = canonicalize_utc_datetime(capture_started_at)
    if not started_at or started_at >= kickoff_at:
        result.update(capture_status="TIME_UNSAFE", status_reason="CAPTURE_STARTED_AT_OR_AFTER_KICKOFF")
        return result
    finished_at = canonicalize_utc_datetime(capture_finished_at) if capture_finished_at else None
    if capture_finished_at and (not finished_at or finished_at >= kickoff_at):
        result.update(capture_status="TIME_UNSAFE", status_reason="CAPTURE_FINISHED_AT_OR_AFTER_KICKOFF")
        return result
    result.update(capture_status="PREMATCH_VALID", status_reason="")
    return result


def build_history_observation(
    raw_observation: dict[str, Any],
    provider_event_id: str | None,
    kickoff_at: str | None,
    observed_at: str,
    observation_sequence: int,
) -> dict[str, Any]:
    """Wrap one raw observation without deduplication or disposition guessing."""
    observed_utc = canonicalize_utc_datetime(observed_at)
    kickoff_utc = canonicalize_utc_datetime(kickoff_at)
    eligible = bool(observed_utc and kickoff_utc and observed_utc < kickoff_utc)
    return {
        "schema_version": SCHEMA_VERSION,
        "provider": PROVIDER,
        "provider_event_id": provider_event_id,
        "observed_at": observed_utc or observed_at,
        "observation_sequence": observation_sequence,
        "observation_id": str(raw_observation.get("raw_record_id") or f"observation:{observation_sequence}"),
        "raw_record_id": raw_observation.get("raw_record_id"),
        "source_raw_record_ids": list(raw_observation.get("source_raw_record_ids") or []),
        "disposition": "PENDING",
        "disposition_reason": None,
        "prematch_eligible": eligible,
        "prematch_ineligible_reason": None if eligible else "QUOTE_AT_OR_AFTER_KICKOFF",
        "raw_observation": copy.deepcopy(raw_observation),
    }


def write_history_sidecars(history_dir: Path, run_payload: dict[str, Any], observations: list[dict[str, Any]]) -> dict[str, str]:
    """Create immutable per-run sidecars. Existing run IDs are never overwritten."""
    history_dir.mkdir(parents=True, exist_ok=True)
    run_id = str(run_payload.get("run_id") or "")
    if not run_id:
        raise ValueError("run_id is required for history sidecar")
    run_path = history_dir / f"history_run_{run_id}.json"
    observations_path = history_dir / f"history_observations_{run_id}.jsonl"
    with run_path.open("x", encoding="utf-8") as handle:
        json.dump(run_payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
    try:
        with observations_path.open("x", encoding="utf-8") as handle:
            for observation in observations:
                handle.write(json.dumps(observation, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    except Exception:
        run_path.unlink(missing_ok=True)
        raise
    return {"run_sidecar_path": str(run_path), "observations_sidecar_path": str(observations_path)}
