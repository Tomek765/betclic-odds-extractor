"""PATCH_C identity bridges from Betclic capture evidence to an upstream event.

An identity bridge is evidence, not a label.  Only a bridge whose mapping is
embedded by Betclic for the same provider event can classify a foreign source
as ``EXACT_PROVIDER_DERIVED``.  Team names, score and kickoff are deliberately
not accepted as identity proof.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from snapshot_manifest_v0_1 import canonical_json_bytes
from history_contract_v0_1 import canonicalize_utc_datetime


SCHEMA_VERSION = "APEX_IDENTITY_BRIDGE_V0_1"
EXACT_PROVIDER_DERIVED = "EXACT_PROVIDER_DERIVED"
EXACT_CROSS_PROVIDER = "EXACT_CROSS_PROVIDER"
UNVERIFIED = "UNVERIFIED"
REJECTED = "REJECTED"
APPROVED_CLASSES = frozenset({EXACT_PROVIDER_DERIVED, EXACT_CROSS_PROVIDER})
_REF_RE = re.compile(r'"externalMatchRef"\s*:\s*"([0-9]+)"')
_SPORT_RE = re.compile(r'"externalSportRef"\s*:\s*"([0-9]+)"')


class IdentityBridgeValidationError(ValueError):
    pass


def _sha(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def validate_bridge_integrity(bridge: dict[str, Any]) -> None:
    """Verify that the published bridge identity still names its exact evidence."""
    base_keys = (
        "schema_version", "provider", "provider_event_id", "upstream_provider",
        "upstream_event_id", "upstream_sport_id", "identity_class", "captured_at",
        "source", "evidence",
    )
    if not isinstance(bridge, dict) or any(key not in bridge for key in base_keys):
        raise IdentityBridgeValidationError("complete bridge evidence required")
    base = {key: bridge[key] for key in base_keys}
    expected_sha = _sha(base)
    expected_id = f"apex-identity-bridge-v0.1:{expected_sha[:32]}"
    evidence = bridge.get("evidence")
    source = bridge.get("source")
    if (bridge.get("bridge_sha256") != expected_sha or bridge.get("bridge_id") != expected_id
            or not isinstance(evidence, dict) or not isinstance(source, dict)
            or source.get("evidence_sha256") != _sha(evidence)):
        raise IdentityBridgeValidationError("bridge identity does not match immutable evidence")


def extract_betclic_sportradar_reference(html: str | None, provider_event_id: str | None) -> dict[str, str] | None:
    """Read a unique, provider-embedded Sportradar reference; ambiguity fails closed."""
    if not isinstance(html, str) or not provider_event_id:
        return None
    # ``provider_event_id`` must occur in the captured source.  We do not
    # infer an association from the URL, names, score, or a nearby event.
    if f'"matchId":"{provider_event_id}"' not in html:
        return None
    refs, sports = set(_REF_RE.findall(html)), set(_SPORT_RE.findall(html))
    if len(refs) != 1 or len(sports) != 1:
        return None
    return {"upstream_provider": "SPORTRADAR", "upstream_event_id": next(iter(refs)),
            "upstream_sport_id": next(iter(sports))}


def build_provider_derived_bridge(provider_event_id: str, html: str, source_logical_path: str,
                                  captured_at: str | None = None) -> dict[str, Any]:
    """Build deterministic evidence from the Betclic hydration payload itself."""
    reference = extract_betclic_sportradar_reference(html, provider_event_id)
    captured_utc = canonicalize_utc_datetime(captured_at) if captured_at else None
    if not reference or not source_logical_path or (captured_at is not None and not captured_utc):
        raise IdentityBridgeValidationError("unique provider-embedded upstream reference required")
    evidence = {"provider_event_id": provider_event_id, **reference}
    base = {
        "schema_version": SCHEMA_VERSION,
        "provider": "BETCLIC",
        "provider_event_id": provider_event_id,
        "upstream_provider": reference["upstream_provider"],
        "upstream_event_id": reference["upstream_event_id"],
        "upstream_sport_id": reference["upstream_sport_id"],
        "identity_class": EXACT_PROVIDER_DERIVED,
        "captured_at": captured_utc,
        "source": {"logical_path": source_logical_path,
                   "sha256": hashlib.sha256(html.encode("utf-8")).hexdigest(),
                   "evidence_sha256": _sha(evidence)},
        "evidence": evidence,
    }
    return {**base, "bridge_id": f"apex-identity-bridge-v0.1:{_sha(base)[:32]}", "bridge_sha256": _sha(base)}


def validate_bridge_for_label(bridge: dict[str, Any], provider_event_id: str, upstream_provider: str,
                              upstream_event_id: str, upstream_sport_id: str | None = None) -> None:
    """Require the exact, approved mapping before a foreign label is canonical."""
    validate_bridge_integrity(bridge)
    if bridge.get("identity_class") not in APPROVED_CLASSES:
        raise IdentityBridgeValidationError("identity bridge is not approved")
    expected = (provider_event_id, upstream_provider, upstream_event_id)
    actual = (bridge.get("provider_event_id"), bridge.get("upstream_provider"), bridge.get("upstream_event_id"))
    if actual != expected:
        raise IdentityBridgeValidationError("identity bridge does not match label source")
    if upstream_sport_id is not None and bridge.get("upstream_sport_id") != upstream_sport_id:
        raise IdentityBridgeValidationError("upstream sport namespace does not match label source")


def validate_one_to_one_bridges(bridges: list[dict[str, Any]]) -> None:
    """Reject conflicting approved mappings in one provider/upstream namespace."""
    provider_to_upstream: dict[tuple[str, str], tuple[str, str]] = {}
    upstream_to_provider: dict[tuple[str, str, str], str] = {}
    for bridge in bridges:
        if bridge.get("identity_class") not in APPROVED_CLASSES:
            continue
        provider_key = (str(bridge.get("provider")), str(bridge.get("provider_event_id")))
        upstream_key = (str(bridge.get("upstream_provider")), str(bridge.get("upstream_sport_id")), str(bridge.get("upstream_event_id")))
        upstream_value = (upstream_key[0], upstream_key[2])
        if provider_key in provider_to_upstream and provider_to_upstream[provider_key] != upstream_value:
            raise IdentityBridgeValidationError("provider event maps to multiple upstream events")
        if upstream_key in upstream_to_provider and upstream_to_provider[upstream_key] != provider_key[1]:
            raise IdentityBridgeValidationError("upstream event maps to multiple provider events")
        provider_to_upstream[provider_key] = upstream_value
        upstream_to_provider[upstream_key] = provider_key[1]


def write_bridge_append_only(directory: Path, bridge: dict[str, Any]) -> Path:
    """Persist one immutable bridge; same deterministic identity may not overwrite."""
    validate_bridge_integrity(bridge)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"identity_bridge_{bridge['bridge_sha256']}.json"
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(bridge, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
    return path


def load_exact_persisted_bridge(directory: Path, provider_event_id: str) -> dict[str, Any]:
    """Load one integrity-validated prior bridge for the same provider event.

    This is deliberately fail-closed: a current live page may omit hydration,
    but it must never select a bridge by names, score, or an arbitrary file.
    """
    if not provider_event_id:
        raise IdentityBridgeValidationError("provider event identity required")
    candidates: list[dict[str, Any]] = []
    for path in sorted(directory.glob("identity_bridge_*.json")):
        try:
            bridge = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise IdentityBridgeValidationError("persisted bridge cannot be read") from exc
        if bridge.get("provider_event_id") != provider_event_id:
            continue
        validate_bridge_for_label(
            bridge, provider_event_id, bridge.get("upstream_provider"),
            bridge.get("upstream_event_id"), bridge.get("upstream_sport_id"),
        )
        candidates.append(bridge)
    if len(candidates) != 1:
        raise IdentityBridgeValidationError("one exact persisted bridge required")
    return candidates[0]
