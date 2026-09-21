"""PATCH_B deterministic, lossless snapshot manifests for History Contract V0.1."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from history_contract_v0_1 import canonicalize_utc_datetime


SCHEMA_VERSION = "APEX_HISTORY_SNAPSHOT_MANIFEST_V0_1"
CANONICALIZATION_VERSION = "APEX_CANONICAL_SNAPSHOT_V0_1"


class SnapshotValidationError(ValueError):
    """Raised when a raw run cannot safely become a canonical prematch snapshot."""


def _normalise(value: Any) -> Any:
    """Canonical, typed JSON value; dict insertion and host locale cannot affect it."""
    if value is None:
        return ["null"]
    if isinstance(value, bool):
        return ["bool", value]
    if isinstance(value, int):
        return ["int", str(value)]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SnapshotValidationError("non-finite float cannot be canonicalized")
        return ["float", repr(value)]
    if isinstance(value, str):
        return ["str", unicodedata.normalize("NFC", value)]
    if isinstance(value, list):
        return ["list", [_normalise(item) for item in value]]
    if isinstance(value, dict):
        pairs: list[tuple[str, Any]] = []
        seen: set[str] = set()
        for key, item in value.items():
            if not isinstance(key, str):
                raise SnapshotValidationError("non-string object key cannot be canonicalized")
            canonical_key = unicodedata.normalize("NFC", key)
            if canonical_key in seen:
                raise SnapshotValidationError("Unicode-normalized object-key collision")
            seen.add(canonical_key)
            pairs.append((canonical_key, _normalise(item)))
        return ["object", [[key, item] for key, item in sorted(pairs)]]
    raise SnapshotValidationError(f"unsupported canonical value type: {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    """UTF-8, NFC, typed, sorted-object canonical serialization with LF-free bytes."""
    return json.dumps(_normalise(value), ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def sha256_canonical(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _artifact_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line:
            item = json.loads(line)
            if not isinstance(item, dict):
                raise SnapshotValidationError(f"observation line {number} is not an object")
            rows.append(item)
    return rows


def _canonical_timestamp(value: Any, label: str) -> str:
    canonical = canonicalize_utc_datetime(value if isinstance(value, str) else None)
    if not canonical:
        raise SnapshotValidationError(f"{label} is missing, naive, or invalid")
    return canonical


def _observation_identity(observation: dict[str, Any], run_id: str) -> dict[str, str]:
    raw = observation.get("raw_observation")
    if not isinstance(raw, dict):
        raise SnapshotValidationError("raw_observation is required for provenance")
    source_observation_id = observation.get("observation_id")
    raw_record_id = observation.get("raw_record_id")
    sequence = observation.get("observation_sequence")
    observed_at = _canonical_timestamp(observation.get("observed_at"), "observed_at")
    if not isinstance(source_observation_id, str) or not source_observation_id:
        raise SnapshotValidationError("observation_id is required")
    if not isinstance(raw_record_id, str) or not raw_record_id:
        raise SnapshotValidationError("raw_record_id is required")
    if not isinstance(sequence, int) or sequence < 1:
        raise SnapshotValidationError("observation_sequence must be a positive integer")
    # ``raw`` is the provider/DOM quote payload.  Lineage fields such as
    # raw_record_id intentionally stay outside this content identity so equal
    # quote payloads can be counted without collapsing their occurrences.
    content_fingerprint = sha256_canonical(raw.get("raw") if "raw" in raw else raw)
    occurrence_id = sha256_canonical({
        "contract": CANONICALIZATION_VERSION,
        "run_id": run_id,
        "source_observation_id": source_observation_id,
        "raw_record_id": raw_record_id,
        "observation_sequence": sequence,
        "observed_at": observed_at,
        "content_fingerprint": content_fingerprint,
    })
    return {
        "content_fingerprint": content_fingerprint,
        "occurrence_id": occurrence_id,
        "observed_at": observed_at,
    }


def _validate_run(run: dict[str, Any], observations: list[dict[str, Any]]) -> tuple[str, str]:
    run_id = run.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise SnapshotValidationError("run_id is required")
    kickoff_at = _canonical_timestamp(run.get("kickoff_at"), "kickoff_at")
    if run.get("capture_status") != "PREMATCH_VALID":
        raise SnapshotValidationError("capture_status is not PREMATCH_VALID")
    identity = run.get("identity_validation")
    if not isinstance(identity, dict) or identity.get("exact_match") is not True:
        raise SnapshotValidationError("provider identity is not exact")
    if not run.get("provider_event_id"):
        raise SnapshotValidationError("provider_event_id is required")
    if not observations:
        raise SnapshotValidationError("accepted prematch snapshot cannot be empty")
    return run_id, kickoff_at


def canonical_snapshot(run: dict[str, Any], observations: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the hashable artifact payload, retaining every occurrence and its lineage."""
    run_id, kickoff_at = _validate_run(run, observations)
    rows: list[dict[str, Any]] = []
    occurrence_ids: set[str] = set()
    raw_ids: set[str] = set()
    for observation in observations:
        identity = _observation_identity(observation, run_id)
        occurrence_id = identity["occurrence_id"]
        raw_record_id = str(observation["raw_record_id"])
        if occurrence_id in occurrence_ids or raw_record_id in raw_ids:
            raise SnapshotValidationError("duplicate occurrence or raw_record_id is ambiguous")
        occurrence_ids.add(occurrence_id)
        raw_ids.add(raw_record_id)
        if observation.get("provider_event_id") != run["provider_event_id"]:
            raise SnapshotValidationError("observation provider_event_id does not match run")
        if observation.get("prematch_eligible") is not True:
            raise SnapshotValidationError("ineligible observation cannot enter canonical prematch snapshot")
        if identity["observed_at"] >= kickoff_at:
            raise SnapshotValidationError("observation at or after kickoff cannot enter prematch snapshot")
        source_hash = observation["raw_observation"].get("source_hash")
        if not isinstance(source_hash, str) or not source_hash:
            raise SnapshotValidationError("source_hash is required for provenance")
        canonical_occurrence = dict(observation)
        canonical_occurrence["observed_at"] = identity["observed_at"]
        rows.append({
            "content_fingerprint": identity["content_fingerprint"],
            "occurrence_id": occurrence_id,
            "observed_at": identity["observed_at"],
            "occurrence": canonical_occurrence,
        })
    rows.sort(key=lambda item: item["occurrence_id"])
    cutoff = max(item["observed_at"] for item in rows)
    if cutoff >= kickoff_at:
        raise SnapshotValidationError("snapshot_cutoff_at must precede kickoff_at")
    return {
        "canonicalization_version": CANONICALIZATION_VERSION,
        "run": run,
        "snapshot_cutoff_at": cutoff,
        "observations": rows,
    }


def build_manifest(run: dict[str, Any], observations: list[dict[str, Any]], source_artifacts: dict[str, Any]) -> dict[str, Any]:
    snapshot = canonical_snapshot(run, observations)
    snapshot_sha256 = sha256_canonical(snapshot)
    duplicate_counter = Counter(item["content_fingerprint"] for item in snapshot["observations"])
    counts = Counter(str(item["occurrence"].get("disposition") or "PENDING") for item in snapshot["observations"])
    return {
        "schema_version": SCHEMA_VERSION,
        "contract_version": "APEX_HISTORY_COLLECTION_CONTRACT_V0_1",
        "canonicalization_version": CANONICALIZATION_VERSION,
        "snapshot_id": f"apex-snapshot-v0.1:{snapshot_sha256[:32]}",
        "run_id": run["run_id"],
        "provider": run["provider"],
        "provider_event_id": run["provider_event_id"],
        "kickoff_at": _canonical_timestamp(run["kickoff_at"], "kickoff_at"),
        "snapshot_cutoff_at": snapshot["snapshot_cutoff_at"],
        "capture_started_at": _canonical_timestamp(run["capture_started_at"], "capture_started_at"),
        "capture_finished_at": _canonical_timestamp(run["capture_finished_at"], "capture_finished_at"),
        "capture_status": run["capture_status"],
        "prematch_verified": True,
        "observation_count": len(snapshot["observations"]),
        "prematch_eligible_count": len(snapshot["observations"]),
        "prematch_ineligible_count": 0,
        "accepted_count": counts["ACCEPTED"], "quarantined_count": counts["QUARANTINED"],
        "rejected_count": counts["REJECTED"], "unresolved_count": counts["UNRESOLVED"],
        "pending_count": counts["PENDING"],
        "duplicate_content_group_count": sum(count > 1 for count in duplicate_counter.values()),
        "duplicate_content_occurrence_count": sum(count for count in duplicate_counter.values() if count > 1),
        "snapshot_sha256": snapshot_sha256,
        "semantic_market_state_sha256": None,
        "source_artifacts": source_artifacts,
        "validation": {"status": "CANONICAL_PREMATCH_SNAPSHOT_VALID", "reason_codes": []},
        "canonical_snapshot": snapshot,
        "non_hashed_audit_metadata": {"path_policy": "logical relative artifact labels only"},
    }


def build_manifest_from_sidecars(run_path: Path, observations_path: Path) -> dict[str, Any]:
    run = json.loads(run_path.read_text(encoding="utf-8"))
    observations = _load_jsonl(observations_path)
    return build_manifest(run, observations, {
        "history_run": {"logical_path": f"history_v0_1/{run_path.name}", "sha256": _artifact_sha256(run_path)},
        "history_observations": {"logical_path": f"history_v0_1/{observations_path.name}", "sha256": _artifact_sha256(observations_path)},
    })


def write_manifest(manifest_dir: Path, manifest: dict[str, Any]) -> Path:
    manifest_dir.mkdir(parents=True, exist_ok=True)
    path = manifest_dir / f"history_snapshot_manifest_{manifest['run_id']}.json"
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(manifest, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
    return path


def build_and_write_manifest(run_path: Path, observations_path: Path, manifest_dir: Path) -> Path:
    return write_manifest(manifest_dir, build_manifest_from_sidecars(run_path, observations_path))


def _main() -> int:
    parser = argparse.ArgumentParser(description="Build immutable PATCH_B snapshot manifest from PATCH_A sidecars.")
    parser.add_argument("run_sidecar", type=Path)
    parser.add_argument("observations_sidecar", type=Path)
    parser.add_argument("manifest_dir", type=Path)
    args = parser.parse_args()
    print(build_and_write_manifest(args.run_sidecar, args.observations_sidecar, args.manifest_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
