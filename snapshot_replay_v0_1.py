"""Independent PATCH_B replay verifier.  It deliberately does not import the manifest builder."""
from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from pathlib import Path
from typing import Any

from history_contract_v0_1 import canonicalize_utc_datetime


CANONICALIZATION_VERSION = "APEX_CANONICAL_SNAPSHOT_V0_1"


class ReplayVerificationError(ValueError):
    pass


def _independent_normalise(value: Any) -> Any:
    if value is None:
        return ["null"]
    if isinstance(value, bool):
        return ["bool", value]
    if isinstance(value, int):
        return ["int", str(value)]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ReplayVerificationError("non-finite float")
        return ["float", repr(value)]
    if isinstance(value, str):
        return ["str", unicodedata.normalize("NFC", value)]
    if isinstance(value, list):
        return ["list", [_independent_normalise(item) for item in value]]
    if isinstance(value, dict):
        pairs, seen = [], set()
        for key, item in value.items():
            if not isinstance(key, str):
                raise ReplayVerificationError("non-string key")
            key = unicodedata.normalize("NFC", key)
            if key in seen:
                raise ReplayVerificationError("normalized key collision")
            seen.add(key)
            pairs.append((key, _independent_normalise(item)))
        return ["object", [[key, item] for key, item in sorted(pairs)]]
    raise ReplayVerificationError(f"unsupported type {type(value).__name__}")


def _canonical_sha256(value: Any) -> str:
    body = json.dumps(_independent_normalise(value), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _timestamp(value: Any, label: str) -> str:
    result = canonicalize_utc_datetime(value if isinstance(value, str) else None)
    if not result:
        raise ReplayVerificationError(f"invalid {label}")
    return result


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def independent_canonical_snapshot(run: dict[str, Any], observations: list[dict[str, Any]]) -> dict[str, Any]:
    run_id = run.get("run_id")
    kickoff = _timestamp(run.get("kickoff_at"), "kickoff_at")
    identity = run.get("identity_validation")
    if not isinstance(run_id, str) or not run_id or run.get("capture_status") != "PREMATCH_VALID":
        raise ReplayVerificationError("run is not an accepted prematch capture")
    if not isinstance(identity, dict) or identity.get("exact_match") is not True or not run.get("provider_event_id"):
        raise ReplayVerificationError("unsafe provider identity")
    rows, occurrence_ids, raw_ids = [], set(), set()
    for observation in observations:
        raw = observation.get("raw_observation")
        raw_id, source_id, seq = observation.get("raw_record_id"), observation.get("observation_id"), observation.get("observation_sequence")
        observed = _timestamp(observation.get("observed_at"), "observed_at")
        if not isinstance(raw, dict) or not isinstance(raw_id, str) or not raw_id or not isinstance(source_id, str) or not source_id:
            raise ReplayVerificationError("missing observation provenance")
        if not isinstance(seq, int) or seq < 1 or observation.get("prematch_eligible") is not True or observed >= kickoff:
            raise ReplayVerificationError("invalid prematch observation")
        if observation.get("provider_event_id") != run["provider_event_id"] or not raw.get("source_hash"):
            raise ReplayVerificationError("observation event/provenance mismatch")
        content = _canonical_sha256(raw.get("raw") if "raw" in raw else raw)
        occurrence = _canonical_sha256({
            "contract": CANONICALIZATION_VERSION, "run_id": run_id,
            "source_observation_id": source_id, "raw_record_id": raw_id,
            "observation_sequence": seq, "observed_at": observed,
            "content_fingerprint": content,
        })
        if occurrence in occurrence_ids or raw_id in raw_ids:
            raise ReplayVerificationError("ambiguous occurrence")
        occurrence_ids.add(occurrence); raw_ids.add(raw_id)
        canonical_occurrence = dict(observation)
        canonical_occurrence["observed_at"] = observed
        rows.append({"content_fingerprint": content, "occurrence_id": occurrence,
                     "observed_at": observed, "occurrence": canonical_occurrence})
    if not rows:
        raise ReplayVerificationError("empty snapshot")
    rows.sort(key=lambda row: row["occurrence_id"])
    cutoff = max(row["observed_at"] for row in rows)
    if cutoff >= kickoff:
        raise ReplayVerificationError("snapshot cutoff is not prematch")
    return {"canonicalization_version": CANONICALIZATION_VERSION, "run": run,
            "snapshot_cutoff_at": cutoff, "observations": rows}


def verify_manifest_against_sidecars(manifest_path: Path, run_path: Path, observations_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    run = json.loads(run_path.read_text(encoding="utf-8"))
    observations = _load_jsonl(observations_path)
    replayed = independent_canonical_snapshot(run, observations)
    replay_hash = _canonical_sha256(replayed)
    expected = manifest.get("snapshot_sha256")
    return {
        "valid": bool(replay_hash == expected and manifest.get("canonical_snapshot") == replayed),
        "snapshot_id": manifest.get("snapshot_id"), "expected_snapshot_sha256": expected,
        "replayed_snapshot_sha256": replay_hash, "observation_count": len(observations),
    }
