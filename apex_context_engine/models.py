from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class OddRecord:
    category: str
    family: str
    market: str
    period: str
    owner: str
    selection: str
    line: str
    handicap_kind: str
    handicap_taxonomy: str
    settlement: str
    odds: float
    raw: str = ""
    period_source: str = ""
    period_confidence: str = ""
    scorer_scope: str = ""
    canonical_outcome: str = ""
    market_instance: str = ""
    source_index: int = 0
    participant: str = ""
    source_raw_record_ids: tuple[str, ...] = ()
    event_teams: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ParsedPacket:
    header: dict[str, str]
    odds: list[OddRecord]
    equivalence_groups_raw: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    normalized_text_sha256: str = ""
    source_odd_count: int = 0
    quarantined_rows: list[dict[str, Any]] = field(default_factory=list)
    semantic_resolutions: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class FairMarket:
    key: str
    family: str
    market: str
    period: str
    owner: str
    line: str
    handicap_kind: str
    handicap_taxonomy: str
    settlement: str
    method: str
    method_detail: dict[str, Any]
    selections: dict[str, float]
    raw_implied: dict[str, float]
    source_odds: dict[str, float]
    overround: float
    quality: str = "VALID"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ContextPacket:
    schema_version: str
    engine_version: str
    status: str
    blocked_reasons: list[str]
    input_sha256: str
    input_truth: dict[str, Any]
    fair_markets: list[dict[str, Any]]
    market_graph: dict[str, Any]
    equivalence_audit: dict[str, Any]
    best_price_alerts: list[dict[str, Any]]
    market_script: dict[str, Any]
    offense_map: dict[str, Any]
    line_discipline: dict[str, Any]
    anomalies: list[dict[str, Any]]
    warnings: list[str]
    accepted_rows: int
    quarantined_rows: list[dict[str, Any]]
    quarantine_reasons: dict[str, int]
    core_coverage: dict[str, Any]
    optional_coverage: dict[str, Any]
    unsupported_families: list[str]
    semantic_resolutions: list[dict[str, Any]]
    source_odd_rows: int
    quarantined_source_rows: int
    upstream_excluded_rows: int
    total_observed_rows: int
    semantic_safety_quarantine: list[dict[str, Any]]
    upstream_exclusions: list[dict[str, Any]] = field(default_factory=list)
    warning_dispositions: list[dict[str, str]] = field(default_factory=list)
    not_modeled_rows: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
