"""PATCH_B.1 append-only decisions for immutable PATCH_B occurrences."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from history_contract_v0_1 import canonicalize_utc_datetime
from snapshot_manifest_v0_1 import canonical_json_bytes

SCHEMA_VERSION = "APEX_HISTORY_DISPOSITION_LEDGER_V0_1"
DECISIONS = frozenset({"ACCEPTED", "QUARANTINED", "REJECTED", "UNRESOLVED"})

class LedgerValidationError(ValueError): pass

def _hash(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()

def load_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.exists(): return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]

def _target(manifest: dict[str, Any], occurrence_id: str) -> dict[str, Any]:
    if not isinstance(occurrence_id, str) or not occurrence_id: raise LedgerValidationError("occurrence_id required")
    found = [row for row in manifest.get("canonical_snapshot", {}).get("observations", []) if row.get("occurrence_id") == occurrence_id]
    if len(found) != 1: raise LedgerValidationError("unknown or ambiguous occurrence_id")
    return found[0]["occurrence"]

def create_annotation(manifest: dict[str, Any], occurrence_id: str, decision: str, reason_code: str,
                      decision_source: str, decision_stage: str, decision_observed_at: str,
                      source_artifact: dict[str, str], reason_detail: str | None = None,
                      supersedes_annotation_id: str | None = None) -> dict[str, Any]:
    if decision not in DECISIONS: raise LedgerValidationError("invalid decision")
    if not all(isinstance(value, str) and value for value in (reason_code, decision_source, decision_stage)):
        raise LedgerValidationError("reason_code, decision_source and decision_stage required")
    at = canonicalize_utc_datetime(decision_observed_at)
    if not at: raise LedgerValidationError("decision_observed_at invalid")
    if not isinstance(source_artifact, dict) or not source_artifact.get("logical_path") or not source_artifact.get("sha256"):
        raise LedgerValidationError("decision source artifact logical_path and sha256 required")
    occurrence = _target(manifest, occurrence_id)
    payload = {"schema_version": SCHEMA_VERSION, "snapshot_id": manifest["snapshot_id"],
        "run_id": manifest["run_id"], "provider_event_id": manifest["provider_event_id"],
        "occurrence_id": occurrence_id, "observation_id": occurrence["observation_id"],
        "raw_record_id": occurrence["raw_record_id"], "decision": decision, "reason_code": reason_code,
        "reason_detail": reason_detail, "decision_source": decision_source, "decision_stage": decision_stage,
        "decision_observed_at": at, "supersedes_annotation_id": supersedes_annotation_id,
        "source_artifact": {"logical_path": source_artifact["logical_path"], "sha256": source_artifact["sha256"]}}
    payload_hash = _hash(payload)
    return {**payload, "annotation_payload_hash": payload_hash, "annotation_id": f"apex-disposition-v0.1:{payload_hash[:32]}"}

def validate_append(manifest: dict[str, Any], existing: list[dict[str, Any]], annotation: dict[str, Any]) -> None:
    _target(manifest, annotation.get("occurrence_id"))
    for key in ("snapshot_id", "run_id", "provider_event_id"):
        if annotation.get(key) != manifest.get(key): raise LedgerValidationError("cross-snapshot/event annotation")
    ids = {row.get("annotation_id") for row in existing}
    if annotation["annotation_id"] in ids: raise LedgerValidationError("annotation already exists")
    by_id = {row.get("annotation_id"): row for row in existing}
    supersedes = annotation.get("supersedes_annotation_id")
    same_target = [row for row in existing if row.get("occurrence_id") == annotation["occurrence_id"]]
    superseded = {row.get("supersedes_annotation_id") for row in existing if row.get("supersedes_annotation_id")}
    active = [row for row in same_target if row.get("annotation_id") not in superseded]
    if supersedes:
        prior = by_id.get(supersedes)
        if not prior or prior.get("occurrence_id") != annotation["occurrence_id"]: raise LedgerValidationError("invalid supersession target")
    elif active:
        raise LedgerValidationError("active decision requires explicit supersession")
    # Existing records must be acyclic before they can be extended.
    for row in existing:
        seen, current = set(), row.get("annotation_id")
        while current:
            if current in seen: raise LedgerValidationError("supersession cycle")
            seen.add(current); current = by_id.get(current, {}).get("supersedes_annotation_id")

def append_annotation(path: Path, manifest: dict[str, Any], annotation: dict[str, Any]) -> str:
    existing = load_ledger(path); validate_append(manifest, existing, annotation)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(annotation, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    return _hash(sorted([row["annotation_id"] for row in existing + [annotation]]))

def active_annotations(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    superseded = {row.get("supersedes_annotation_id") for row in rows}
    active = [row for row in rows if row.get("annotation_id") not in superseded]
    result = {row["occurrence_id"]: row for row in active}
    if len(result) != len(active): raise LedgerValidationError("contradictory active decisions")
    return result
