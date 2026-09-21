from __future__ import annotations

import math
import statistics
from typing import Iterable

from .models import FairMarket
from .poisson import invert_over_probability, probability_at_least, top_scores


def _find(markets: Iterable[FairMarket], family: str, *, period: str = "FULL_TIME", owner: str | None = None, line: str | None = None) -> FairMarket | None:
    matches = [m for m in markets if m.family == family and m.period == period and (owner is None or m.owner == owner) and (line is None or m.line == line)]
    return sorted(matches, key=lambda m: m.key)[0] if matches else None


def _prob(market: FairMarket | None, names: tuple[str, ...]) -> float | None:
    if market is None:
        return None
    for name in names:
        if name in market.selections:
            return market.selections[name]
    return None


def _teams(match: str) -> tuple[str | None, str | None]:
    for separator in (" - ", " vs ", " v "):
        if separator in match:
            home, away = (part.strip() for part in match.split(separator, 1))
            if home and away and home != away:
                return home, away
    return None, None


def _strength_labels(probabilities: dict[str, float]) -> tuple[str, str]:
    draw = probabilities.get("DRAW", 0.0)
    favorite = max(probabilities.get("HOME", 0.0), probabilities.get("AWAY", 0.0))
    draw_gravity = "HIGH" if draw >= 0.30 else "MEDIUM" if draw >= 0.24 else "LOW"
    favorite_strength = "STRONG" if favorite >= 0.62 else "MODERATE" if favorite >= 0.50 else "BALANCED"
    return draw_gravity, favorite_strength


def _lambda_fit(markets: list[FairMarket]) -> dict:
    estimates = []
    for market in markets:
        try:
            line = float(market.line)
        except (TypeError, ValueError):
            continue
        if abs(line % 1 - 0.5) > 1e-9:
            continue
        probability = _prob(market, ("OVER",))
        if probability is None or not 0 < probability < 1:
            continue
        value = invert_over_probability(line, probability)
        weight = max(0.05, 1.0 / max(1.0, market.overround))
        estimates.append({"line": line, "lambda": value, "weight": weight, "source": market.key})
    if not estimates:
        return {"lambda": None, "sources": [], "dispersion": None, "fit_residual": None, "confidence": "INSUFFICIENT"}
    ordered = sorted(estimates, key=lambda row: (row["lambda"], row["line"], row["source"]))
    midpoint, running = sum(row["weight"] for row in ordered) / 2.0, 0.0
    estimate = ordered[-1]["lambda"]
    for row in ordered:
        running += row["weight"]
        if running >= midpoint:
            estimate = row["lambda"]
            break
    residual = math.sqrt(sum(row["weight"] * (row["lambda"] - estimate) ** 2 for row in ordered) / sum(row["weight"] for row in ordered))
    dispersion = statistics.median(abs(row["lambda"] - estimate) for row in ordered)
    confidence = "HIGH" if len(ordered) >= 3 and residual <= 0.35 else "MEDIUM" if len(ordered) >= 2 else "LOW"
    return {"lambda": estimate, "sources": [{"line": row["line"], "implied_lambda": round(row["lambda"], 6), "market": row["source"]} for row in sorted(ordered, key=lambda row: row["line"])], "dispersion": round(dispersion, 6), "fit_residual": round(residual, 6), "confidence": confidence}


def infer_market_script(header: dict[str, str], fair_markets: list[FairMarket]) -> tuple[dict, list[str]]:
    warnings: list[str] = []
    home, away = _teams(header.get("MATCH", ""))
    if not home or not away:
        return {"status": "UNAVAILABLE", "quality": "BLOCKED", "sources": [], "limitations": ["MATCH_TEAMS_NOT_UNAMBIGUOUS"], "home": home, "away": away}, ["MATCH_TEAMS_NOT_UNAMBIGUOUS"]

    one_x_two = _find(fair_markets, "1X2")
    fair_1x2 = one_x_two.selections if one_x_two else {}
    draw_gravity, favorite_strength = _strength_labels(fair_1x2) if fair_1x2 else ("UNKNOWN", "UNKNOWN")
    sources: list[str] = [one_x_two.key] if one_x_two else []

    home_fit = _lambda_fit([m for m in fair_markets if m.family == "TEAM_TOTALS_HOME" and m.period == "FULL_TIME" and m.owner == home])
    away_fit = _lambda_fit([m for m in fair_markets if m.family == "TEAM_TOTALS_AWAY" and m.period == "FULL_TIME" and m.owner == away])
    total_fit = _lambda_fit([m for m in fair_markets if m.family == "GOALS_OU" and m.period == "FULL_TIME" and not m.owner])
    lambda_home, lambda_away, lambda_total_market = home_fit["lambda"], away_fit["lambda"], total_fit["lambda"]
    sources.extend(row["market"] for fit in (home_fit, away_fit, total_fit) for row in fit["sources"])

    limitations: list[str] = []
    if lambda_home is None or lambda_away is None:
        limitations.append("COMPLETE_TEAM_TOTAL_HALF_LINE_PAIR_REQUIRED_FOR_TEAM_LAMBDAS")
        warnings.append("INSUFFICIENT_MARKETS_FOR_TEAM_LAMBDAS")
        lambda_total = lambda_total_market
    else:
        team_sum = lambda_home + lambda_away
        lambda_total = (team_sum + lambda_total_market) / 2.0 if lambda_total_market is not None else team_sum
        if lambda_total_market is not None and abs(team_sum - lambda_total_market) > 0.45:
            warnings.append("TOTAL_VS_TEAM_TOTAL_LAMBDA_TENSION")
            limitations.append("LAMBDA_SOURCES_DISAGREE_NO_SILENT_BLEND")

    quality = "HIGH" if lambda_home is not None and lambda_away is not None and lambda_total_market is not None else "PARTIAL" if lambda_total is not None else "INSUFFICIENT"
    environment = "UNKNOWN"
    if lambda_total is not None:
        environment = "LOW" if lambda_total < 2.0 else "MEDIUM" if lambda_total < 2.75 else "HIGH" if lambda_total < 3.4 else "VERY_HIGH"
    central = []
    if lambda_home is not None and lambda_away is not None:
        central = [{"score": row["score"], "probability": round(row["probability"], 6)} for row in top_scores(lambda_home, lambda_away)]

    half_distribution: dict = {"status": "INSUFFICIENT_DATA"}
    first_total = _find(fair_markets, "GOALS_OU", period="1ST_HALF", owner="", line="0.5")
    second_total = _find(fair_markets, "GOALS_OU", period="2ND_HALF", owner="", line="0.5")
    first_over, second_over = _prob(first_total, ("OVER",)), _prob(second_total, ("OVER",))
    if first_over is not None and second_over is not None:
        first_lam, second_lam = -math.log1p(-first_over), -math.log1p(-second_over)
        denom = first_lam + second_lam
        half_distribution = {"status": "READY", "lambda_first_half": round(first_lam, 6), "lambda_second_half": round(second_lam, 6), "first_half_share": round(first_lam / denom, 6), "second_half_share": round(second_lam / denom, 6), "sources": [first_total.key, second_total.key]}

    team_component_sum = lambda_home + lambda_away if lambda_home is not None and lambda_away is not None else None
    reconciliation_residual = lambda_total - team_component_sum if lambda_total is not None and team_component_sum is not None else None
    reconciliation_method = (
        "EQUAL_WEIGHT_BLEND_TEAM_COMPONENT_SUM_AND_DIRECT_MATCH_TOTAL"
        if team_component_sum is not None and lambda_total_market is not None
        else "TEAM_COMPONENT_SUM" if team_component_sum is not None
        else "DIRECT_MATCH_TOTAL" if lambda_total_market is not None
        else "UNAVAILABLE"
    )
    script = {
        "status": "READY" if quality in {"HIGH", "PARTIAL"} else "UNAVAILABLE", "quality": quality,
        "label": "MARKET_IMPLIED_CONTEXT_ONLY", "home": home, "away": away,
        "fair_1x2": {key: round(value, 6) for key, value in sorted(fair_1x2.items())},
        "draw_gravity": draw_gravity, "favorite_strength": favorite_strength,
        "lambda_home": round(lambda_home, 6) if lambda_home is not None else None,
        "lambda_away": round(lambda_away, 6) if lambda_away is not None else None,
        "lambda_total": round(lambda_total, 6) if lambda_total is not None else None,
        "lambda_total_from_match_market": round(lambda_total_market, 6) if lambda_total_market is not None else None,
        "reconciled_lambda_total": round(lambda_total, 6) if lambda_total is not None else None,
        "lambda_reconciliation_difference": round(lambda_total_market - (lambda_home + lambda_away), 6) if lambda_total_market is not None and lambda_home is not None and lambda_away is not None else None,
        "team_component_sum": round(team_component_sum, 6) if team_component_sum is not None else None,
        "lambda_reconciliation_residual": round(reconciliation_residual, 6) if reconciliation_residual is not None else None,
        "lambda_reconciliation_residual_percent": round(100.0 * reconciliation_residual / lambda_total, 6) if reconciliation_residual is not None and lambda_total else None,
        "reconciliation_method": reconciliation_method,
        "lambda_sources": {"home": home_fit["sources"], "away": away_fit["sources"], "total": total_fit["sources"]},
        "lambda_fit_residual": {"home": home_fit["fit_residual"], "away": away_fit["fit_residual"], "total": total_fit["fit_residual"]},
        "lambda_dispersion": {"home": home_fit["dispersion"], "away": away_fit["dispersion"], "total": total_fit["dispersion"]},
        "lambda_confidence": {"home": home_fit["confidence"], "away": away_fit["confidence"], "total": total_fit["confidence"]},
        "home_attack_share": round(lambda_home / (lambda_home + lambda_away), 6) if lambda_home is not None and lambda_away is not None else None,
        "away_attack_share": round(lambda_away / (lambda_home + lambda_away), 6) if lambda_home is not None and lambda_away is not None else None,
        "goal_environment": environment, "central_scores": central,
        "goal_probabilities": {
            "home_1plus": round(probability_at_least(1, lambda_home), 6) if lambda_home is not None else None,
            "home_2plus": round(probability_at_least(2, lambda_home), 6) if lambda_home is not None else None,
            "home_3plus": round(probability_at_least(3, lambda_home), 6) if lambda_home is not None else None,
            "away_1plus": round(probability_at_least(1, lambda_away), 6) if lambda_away is not None else None,
            "away_2plus": round(probability_at_least(2, lambda_away), 6) if lambda_away is not None else None,
            "away_3plus": round(probability_at_least(3, lambda_away), 6) if lambda_away is not None else None,
            "match_2plus": round(probability_at_least(2, lambda_total), 6) if lambda_total is not None else None,
            "match_3plus": round(probability_at_least(3, lambda_total), 6) if lambda_total is not None else None,
            "match_4plus": round(probability_at_least(4, lambda_total), 6) if lambda_total is not None else None,
        },
        "goal_milestones": {"third_goal": "MATCH_3PLUS", "fourth_goal": "MATCH_4PLUS"},
        "half_distribution": half_distribution,
        "sources": sorted(set(sources)), "limitations": sorted(set(limitations)),
    }
    return script, sorted(set(warnings))


def _label(probability: float | None) -> str:
    if probability is None:
        return "INSUFFICIENT_DATA"
    if probability >= 0.68:
        return "MARKET_SHORT"
    if probability >= 0.42:
        return "MARKET_BALANCED"
    return "MARKET_LONG"


def build_offense_map(script: dict, markets: list[FairMarket]) -> dict:
    h, a, total = script.get("lambda_home"), script.get("lambda_away"), script.get("lambda_total")
    def poisson_prob(n: int, value: float | None) -> float | None:
        return round(probability_at_least(n, value), 6) if value is not None else None
    metrics = {
        "MATCH_OVER_1_5": poisson_prob(2, total), "MATCH_OVER_2_5": poisson_prob(3, total),
        "HOME_TT_OVER_0_5": poisson_prob(1, h), "HOME_TT_OVER_1_5": poisson_prob(2, h), "HOME_TT_OVER_2_5": poisson_prob(3, h),
        "AWAY_TT_OVER_0_5": poisson_prob(1, a), "AWAY_TT_OVER_1_5": poisson_prob(2, a),
    }
    btts = _find(markets, "BTTS")
    metrics["BTTS_YES"] = _prob(btts, ("YES", "TAK"))
    result = {key: {"probability": value, "label": _label(value)} for key, value in sorted(metrics.items())}
    periods = {}
    for period in ("1ST_HALF", "2ND_HALF"):
        market = _find(markets, "GOALS_OU", period=period, owner="", line="0.5")
        probability = _prob(market, ("OVER",))
        periods[period] = {"probability": probability, "label": _label(probability), "source": market.key if market else None}
    return {"status": "READY" if any(value is not None for value in metrics.values()) else "INSUFFICIENT_DATA", "label": "MARKET_CONTEXT_ONLY", "metrics": result, "period_offense": periods, "primary_scoring_owner": script.get("home") if h is not None and a is not None and h >= a else script.get("away") if h is not None and a is not None else None}


def build_line_discipline(script: dict) -> dict:
    transitions = [
        {"from": "O0.5", "to": "O1.5", "lower_wins_higher_loses": ["1:0", "0:1"]},
        {"from": "O1.5", "to": "O2.5", "lower_wins_higher_loses": ["1:1", "2:0", "0:2"]},
        {"from": "O2.5", "to": "O3.5", "lower_wins_higher_loses": ["2:1", "1:2", "3:0", "0:3"]},
    ]
    scenarios = [
        {"score": "1:0", "effects": ["MATCH_O0_5_WIN", "MATCH_O1_5_LOSE", "HOME_TT_O0_5_WIN", "HIGH_HOME_HANDICAP_MAY_LOSE", "BTTS_YES_LOSE"]},
        {"score": "2:0", "effects": ["MATCH_O1_5_WIN", "MATCH_O2_5_LOSE", "HOME_TT_O1_5_WIN", "BTTS_YES_LOSE"]},
        {"score": "2:1", "effects": ["MATCH_O2_5_WIN", "MATCH_O3_5_LOSE", "BTTS_YES_WIN", "HIGH_HANDICAP_MAY_LOSE"]},
        {"score": "1:1", "effects": ["MATCH_O1_5_WIN", "MATCH_O2_5_LOSE", "BTTS_YES_WIN", "FAVORITE_WIN_LOSE"]},
    ]
    return {"status": "READY" if script.get("lambda_total") is not None else "PARTIAL", "transitions": transitions, "natural_score_scenarios": scenarios, "cross_market_warnings": ["TEAM_TOTAL_CAN_WIN_WHILE_HIGH_HANDICAP_LOSES", "MATCH_OVER_CAN_WIN_WHILE_BTTS_YES_LOSES", "BTTS_YES_CAN_WIN_WHILE_HIGHER_TOTAL_LOSES", "OFFENSIVE_CONTEXT_DOES_NOT_IMPLY_FAVORITE_WIN"], "warnings": ["HIGHER_LINE_REQUIRES_ADDITIONAL_GOAL;CONTEXT_ONLY"]}
