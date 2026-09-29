from __future__ import annotations

from collections import defaultdict

from .models import FairMarket, ParsedPacket
from .market_graph import _market_domain, equivalence_price_contradictions


def line_policy(record, header):
    """Conservative alert ceilings, not acceptance or settlement rules."""
    sport = header.get("SPORT", "FOOTBALL").upper()
    metric = _market_domain(record).removeprefix("STATISTICS:")
    scope = "PLAYER" if record.participant or record.family == "PLAYER_PROP" else "TEAM" if record.owner else "MATCH"
    # "Punkty za kartki" is a booking-points scale (yellow 10, red 25), not a
    # card count, so its lines are ~10x larger than any card-count line.
    if metric == "CARDS" and "punkty za kartki" in record.market.casefold():
        metric = "CARD_POINTS"
    ceilings = {"SHOTS": (20, 50, 80), "SHOTS_ON_TARGET": (10, 25, 40),
                "CORNERS": (10, 25, 40), "CARDS": (3, 15, 25), "CARD_POINTS": (30, 150, 250),
                "FOULS": (15, 40, 70), "OFFSIDES": (10, 20, 30)}
    ceiling = ceilings[metric][("PLAYER", "TEAM", "MATCH").index(scope)] if sport == "FOOTBALL" and metric in ceilings else 10
    if record.period in {"1ST_HALF", "2ND_HALF"}:
        ceiling *= .75
    elif record.period == "MATCH_INCLUDING_EXTRA_TIME":
        ceiling *= 4 / 3
    return {"sport": sport, "statistic": metric, "family": record.family,
            "owner_scope": scope, "period": record.period, "absolute_ceiling": ceiling}


def _handicap_scope(market_name: str) -> str:
    name = market_name.casefold()
    if "rzuty rożne" in name or "rzutów rożnych" in name or "corner" in name:
        return "CORNERS"
    if "kart" in name or "card" in name:
        return "CARDS"
    return "MATCH_SCORE"


def detect_anomalies(packet: ParsedPacket, fair_markets: list[FairMarket], script: dict, alerts: list[dict], equivalence_audit: dict, engine_warnings: list[str]) -> list[dict]:
    anomalies: list[dict] = []
    for alert in alerts:
        anomalies.append({"type": "IDENTICAL_SETTLEMENT_BETTER_PRICE", "severity": "MEDIUM", "evidence": alert})
    for contradiction in equivalence_price_contradictions(packet.odds):
        anomalies.append({"type": "EQUIVALENCE_PRICE_CONTRADICTION", "severity": "HIGH", "evidence": contradiction})
    if "TOTAL_VS_TEAM_TOTAL_LAMBDA_TENSION" in script.get("warnings", []):
        anomalies.append({"type": "TOTAL_VS_TEAM_TOTALS_TENSION", "severity": "MEDIUM", "evidence": {"lambda_total": script.get("lambda_total"), "lambda_total_from_match_market": script.get("lambda_total_from_match_market"), "sources": script.get("sources", [])}})
    for rejected in equivalence_audit.get("rejected_groups", []):
        anomalies.append({"type": "EQUIVALENCE_GROUP_REJECTED", "severity": "HIGH", "evidence": rejected})
    warning_types = {
        "INCOMPLETE_MARKET": "MISSING_REQUIRED_MARKET_PAIR",
        "ODD_UNSUPPORTED_PERIOD": "UNSUPPORTED_PERIOD",
        "TEAM_TOTAL_OWNER_MISSING": "OWNER_MISMATCH",
    }
    for warning in sorted(set(packet.errors + packet.warnings + engine_warnings)):
        for prefix, anomaly_type in warning_types.items():
            if warning.startswith(prefix):
                anomalies.append({"type": anomaly_type, "severity": "HIGH", "evidence": {"reason": warning}})
                break
    # A favorite's win probability and its probability of covering a large
    # handicap are different events.  Only the internal handicap curve is
    # eligible for a consistency alert.
    curves = defaultdict(list)
    for market in fair_markets:
        if market.family not in {"HANDICAP_EUROPEAN", "HANDICAP_ASIAN"}:
            continue
        try:
            home_axis_line = float(market.line)
        except ValueError:
            continue
        for side in ("HOME", "AWAY"):
            if side in market.selections:
                signed_side_line = home_axis_line if side == "HOME" else -home_axis_line
                key = (market.family, market.period, market.handicap_kind, market.settlement, _handicap_scope(market.market), side)
                curves[key].append((signed_side_line, market.selections[side], market.key))
    for (family, period, kind, settlement, scope, side), curve in sorted(curves.items()):
        curve.sort()
        for left, right in zip(curve, curve[1:]):
            if right[1] + 0.035 < left[1]:
                anomalies.append({"type": "HANDICAP_CURVE_NON_MONOTONIC", "severity": "MEDIUM", "evidence": {"family": family, "period": period, "handicap_kind": kind, "settlement": settlement, "scope": scope, "side": side, "lower_line": left[0], "lower_probability": left[1], "higher_line": right[0], "higher_probability": right[1], "sources": [left[2], right[2]], "model": "SIGNED_SIDE_AXIS_ADJACENT_MONOTONICITY"}})
    half = script.get("half_distribution", {})
    if half.get("status") == "READY" and script.get("lambda_total_from_match_market") is not None:
        halves_total = half["lambda_first_half"] + half["lambda_second_half"]
        if abs(halves_total - script["lambda_total_from_match_market"]) > 0.45:
            anomalies.append({"type": "FULL_TIME_VS_HALVES_TENSION", "severity": "MEDIUM", "evidence": {"halves_lambda_total": round(halves_total, 6), "full_time_lambda": script["lambda_total_from_match_market"], "sources": half.get("sources", [])}})
    if script.get("quality") in {"INSUFFICIENT", "BLOCKED"}:
        anomalies.append({"type": "INSUFFICIENT_DATA_QUALITY", "severity": "HIGH", "evidence": {"quality": script.get("quality"), "limitations": script.get("limitations", [])}})
    for record in packet.odds:
        if record.line:
            try:
                policy = line_policy(record, packet.header)
                if abs(float(record.line)) > policy["absolute_ceiling"]:
                    anomalies.append({"type": "SUSPICIOUS_LINE", "severity": "MEDIUM", "evidence": {"line": record.line, "market": record.market, "source_index": record.source_index, "policy": policy}})
            except ValueError:
                pass
    return sorted(anomalies, key=lambda row: (row["type"], str(row["evidence"])))
