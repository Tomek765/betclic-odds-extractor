from __future__ import annotations

from collections import Counter

from .anomalies import detect_anomalies
from .inference import build_line_discipline, build_offense_map, infer_market_script
from .market_graph import audit_equivalence, best_price_alerts, build_fair_markets, build_market_graph, semantic_safety_quarantine
from .models import ContextPacket, ParsedPacket

ENGINE_VERSION = "1.0.0"
_FAIR_CONTEXT_FAMILIES = {
    "1X2", "DNB", "GOALS_OU", "BTTS", "TEAM_TOTALS_HOME", "TEAM_TOTALS_AWAY",
    "HANDICAP_EUROPEAN", "HANDICAP_ASIAN",
}


def _int(header: dict[str, str], key: str, errors: list[str]) -> int | None:
    try:
        return int(header[key])
    except (KeyError, ValueError):
        errors.append(f"INVALID_INTEGER_HEADER:{key}:{header.get(key, '')}")
        return None


def _float(header: dict[str, str], key: str, errors: list[str]) -> float | None:
    try:
        return float(header[key].replace(",", "."))
    except (KeyError, ValueError):
        errors.append(f"INVALID_DECIMAL_HEADER:{key}:{header.get(key, '')}")
        return None


def validate_packet(packet: ParsedPacket) -> tuple[list[str], list[str]]:
    errors = list(packet.errors)
    warnings = list(packet.warnings)
    h = packet.header
    for key in ("MATCH", "COMPETITION"):
        if not h.get(key):
            errors.append(f"MISSING_HEADER_FIELD:{key}")
    parser_truth = h.get("PARSER_TRUTH_STATUS")
    if parser_truth and parser_truth not in {"PASS", "PARTIAL"}:
        warnings.append(f"EXTRACTOR_PARSER_TRUTH_NOT_POSITIVE:{parser_truth}")

    readiness = {key: h.get(key, "").upper() for key in ("CLEAN_CORE_READY", "FULL_USABLE_READY", "ANALYSIS_READY")}
    positive_readiness = {key for key, value in readiness.items() if value == "YES"}
    if not positive_readiness:
        errors.append("EXTRACTOR_READINESS_NOT_POSITIVE")
    if h.get("SOURCE_INCOMPLETE", "").upper() == "YES" and not positive_readiness:
        warnings.append("SOURCE_INCOMPLETE_WITHOUT_EXTRACTOR_USABLE_CORE")

    for key in ("KICKOFF", "PARSER_TRUTH_STATUS", "MARKET_COUNT", "ODDS_COUNT", "UNRESOLVED_COUNT", "COMPLETENESS_SCORE"):
        if not h.get(key):
            warnings.append(f"OPTIONAL_HEADER_FIELD_MISSING:{key}")

    odds_count = _int(h, "ODDS_COUNT", errors) if h.get("ODDS_COUNT") else None
    market_count = _int(h, "MARKET_COUNT", errors) if h.get("MARKET_COUNT") else None
    unresolved = _int(h, "UNRESOLVED_COUNT", errors) if h.get("UNRESOLVED_COUNT") else None
    completeness = _float(h, "COMPLETENESS_SCORE", errors) if h.get("COMPLETENESS_SCORE") else None
    if odds_count is not None and odds_count != packet.source_odd_count:
        errors.append(f"ODDS_COUNT_MISMATCH:HEADER={odds_count}:SOURCE_BLOCKS={packet.source_odd_count}")
    if market_count is not None and market_count <= 0:
        errors.append("MARKET_COUNT_NOT_POSITIVE")
    if unresolved is not None and unresolved > 0:
        warnings.append(f"INPUT_HAS_ROW_LEVEL_UNRESOLVED:{unresolved}")
    if completeness is not None and not 0 <= completeness <= 100:
        errors.append(f"COMPLETENESS_OUT_OF_RANGE:{completeness:g}")

    match = h.get("MATCH", "")
    teams = [part.strip() for part in match.split(" - ", 1)] if " - " in match else []
    if len(teams) != 2 or not all(teams):
        errors.append("MATCH_TEAMS_NOT_UNAMBIGUOUS")
    else:
        home, away = teams
    return sorted(set(errors)), sorted(set(warnings))


def build_context(packet: ParsedPacket) -> ContextPacket:
    blocked, warnings = validate_packet(packet)
    readiness_blocked = "EXTRACTOR_READINESS_NOT_POSITIVE" in blocked
    fair_markets, fair_warnings = build_fair_markets(packet)
    warnings.extend(fair_warnings)
    fair_families = sorted({market.family for market in fair_markets})
    accepted_families = sorted({odd.family for odd in packet.odds})
    has_result_core = any(market.family == "1X2" and market.period == "FULL_TIME" for market in fair_markets)
    has_goal_core = any(market.family in {"GOALS_OU", "BTTS", "TEAM_TOTALS_HOME", "TEAM_TOTALS_AWAY"} for market in fair_markets)
    if not fair_markets:
        blocked.append("NO_SAFE_MARKET_GRAPH")
    if not has_result_core:
        blocked.append("MINIMAL_CORE_MISSING_FULL_TIME_1X2")
    if not has_goal_core:
        blocked.append("MINIMAL_CORE_MISSING_GOAL_MARKET")
    source_quarantine = [row for row in packet.quarantined_rows if row.get("block_type") == "ODD"]
    upstream_exclusions = [row for row in packet.quarantined_rows if row.get("block_type") != "ODD"]
    quarantine_reasons = Counter(reason for row in source_quarantine for reason in row.get("reasons", []))
    quarantined_odds = len(source_quarantine)
    core_coverage = {
        "status": "PASS" if has_result_core and has_goal_core else "FAIL",
        "required": ["FULL_TIME_1X2", "AT_LEAST_ONE_GOAL_MARKET"],
        "full_time_1x2": has_result_core,
        "goal_market": has_goal_core,
        "fair_market_count": len(fair_markets),
        "fair_families": fair_families,
        "team_totals": any(family in fair_families for family in ("TEAM_TOTALS_HOME", "TEAM_TOTALS_AWAY")),
        "half_markets": any(market.period in {"1ST_HALF", "2ND_HALF"} for market in fair_markets),
        "safe_handicaps": any(market.family.startswith("HANDICAP_") for market in fair_markets),
    }
    optional_coverage = {
        "source_odd_rows": packet.source_odd_count,
        "accepted_odd_rows": len(packet.odds),
        "quarantined_odd_rows": quarantined_odds,
        "accepted_ratio": round(len(packet.odds) / packet.source_odd_count, 6) if packet.source_odd_count else 0.0,
    }
    alerts = best_price_alerts(packet.odds)
    safety_quarantine = semantic_safety_quarantine(packet.odds)
    unsafe_indices = {row["source_index"] for row in safety_quarantine}
    fair_keys = {(market.family, market.market, market.period) for market in fair_markets}
    supported_count = sum((row.family, row.market, row.period) in fair_keys
                          for row in packet.odds if row.source_index not in unsafe_indices)
    optional_coverage["disposition_counts"] = {
        "ACCEPTED_SUPPORTED": supported_count,
        "ACCEPTED_NOT_APPLICABLE": len(packet.odds) - len(unsafe_indices) - supported_count,
        "TRUE_QUARANTINE_SOURCE": len(source_quarantine) + len(unsafe_indices),
        "TRUE_QUARANTINE_UPSTREAM": sum(row.get("block_type") == "SEMANTIC_QUARANTINE" for row in upstream_exclusions),
        "AUDITED_EXCLUSION": sum(row.get("block_type") != "SEMANTIC_QUARANTINE" for row in upstream_exclusions),
        "BLOCKING_ERROR": len(blocked),
    }
    optional_coverage["disposition_population"] = (
        "SUPPORTED + NOT_APPLICABLE + TRUE_QUARANTINE_SOURCE = SOURCE_ODD_ROWS; "
        "UPSTREAM and AUDITED_EXCLUSION count emitted upstream blocks; BLOCKING_ERROR counts reasons"
    )
    equivalence = audit_equivalence(packet, alerts)
    if readiness_blocked:
        graph = build_market_graph([])
        script = {"status": "UNAVAILABLE", "quality": "BLOCKED", "fair_1x2": {},
                  "lambda_home": None, "lambda_away": None, "lambda_total": None,
                  "sources": [], "limitations": ["EXTRACTOR_READINESS_NOT_POSITIVE"],
                  "warnings": ["EXTRACTOR_READINESS_NOT_POSITIVE"]}
        offense = {"status": "UNAVAILABLE", "reason": "EXTRACTOR_READINESS_NOT_POSITIVE"}
        line_discipline = {"status": "UNAVAILABLE", "reason": "EXTRACTOR_READINESS_NOT_POSITIVE"}
        anomalies = [{"type": "EXTRACTOR_READINESS_NOT_POSITIVE", "severity": "HIGH", "evidence": {"readiness": "NO"}}]
        core_coverage.update({"status": "FAIL", "full_time_1x2": False, "goal_market": False})
    else:
        graph = build_market_graph(fair_markets)
        script, inference_warnings = infer_market_script(packet.header, fair_markets)
        warnings.extend(inference_warnings)
        script["warnings"] = sorted(set(inference_warnings))
        offense = build_offense_map(script, fair_markets)
        line_discipline = build_line_discipline(script)
        anomalies = detect_anomalies(packet, fair_markets, script, alerts, equivalence, warnings)
    truth_keys = ("MATCH", "COMPETITION", "KICKOFF", "PARSER_TRUTH_STATUS", "ANALYSIS_READY", "CLEAN_CORE_READY", "FULL_USABLE_READY", "MARKET_COUNT", "ODDS_COUNT", "UNRESOLVED_COUNT", "COMPLETENESS_SCORE")
    truth = {key: packet.header.get(key) for key in truth_keys}
    truth["normalized_input_sha256"] = packet.normalized_text_sha256
    status = "BLOCKED" if blocked else "PASS_WITH_QUARANTINE" if (source_quarantine or upstream_exclusions or safety_quarantine) else "PASS"
    truth["context_core_status"] = status
    return ContextPacket(
        schema_version="1.0.0", engine_version=ENGINE_VERSION, status=status,
        blocked_reasons=blocked, input_sha256=packet.normalized_text_sha256, input_truth=truth,
        fair_markets=[] if readiness_blocked else [market.to_dict() for market in fair_markets], market_graph=graph,
        equivalence_audit=equivalence, best_price_alerts=[] if readiness_blocked else alerts, market_script=script,
        offense_map=offense, line_discipline=line_discipline, anomalies=anomalies,
        warnings=sorted(set(warnings)),
        accepted_rows=len(packet.odds), quarantined_rows=source_quarantine,
        quarantine_reasons=dict(sorted(quarantine_reasons.items())), core_coverage=core_coverage,
        optional_coverage=optional_coverage,
        unsupported_families=sorted(set(accepted_families) - _FAIR_CONTEXT_FAMILIES),
        semantic_resolutions=packet.semantic_resolutions,
        source_odd_rows=packet.source_odd_count,
        quarantined_source_rows=quarantined_odds,
        upstream_excluded_rows=len(upstream_exclusions),
        total_observed_rows=packet.source_odd_count + len(upstream_exclusions),
        semantic_safety_quarantine=safety_quarantine,
        upstream_exclusions=upstream_exclusions,
        warning_dispositions=[{"warning": warning,
            "disposition": "ACCEPTED_NOT_APPLICABLE" if warning.startswith((
                "DEVIG_UNSUPPORTED_FAMILY:", "NON_FOOTBALL_FAIR_MARKET_REJECTED:"))
            else "AUDITED_EXCLUSION",
            "scope": "FAIR_MARKET_MODULE" if warning.startswith((
                "DEVIG_UNSUPPORTED_FAMILY:", "NON_FOOTBALL_FAIR_MARKET_REJECTED:"))
            else "DIAGNOSTIC"} for warning in sorted(set(warnings))],
    )
