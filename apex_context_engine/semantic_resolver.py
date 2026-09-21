from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


RULE_SOURCE = "APEX_V1_CLOSED_RULE_TABLE_FROM_EXTRACTOR_TAXONOMY_AND_CONTRACT_TESTS"
KNOWN_SETTLEMENTS = {
    "WIN_LOSE", "WIN_DRAW_LOSE", "PUSH_ON_DRAW", "NO_PUSH", "PUSH_POSSIBLE",
    "ASIAN_SPLIT", "VOID_POSSIBLE", "EACH_WAY", "DEAD_HEAT_APPLIES",
}


def _audit(rule_id: str, field: str, value: str, inputs: dict[str, str], explicit: bool) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "field": field,
        "value": value,
        "inputs": {key: inputs.get(key, "") for key in sorted(inputs)},
        "source": RULE_SOURCE,
        "confidence": "EXACT",
        "origin": "EXPLICIT" if explicit else "CANONICALLY_DERIVED",
    }


def _line_class(line: str) -> str:
    try:
        value = abs(Decimal(line.replace(",", ".")))
    except InvalidOperation:
        return "INVALID"
    fraction = value % 1
    if fraction == 0:
        return "INTEGER"
    if fraction == Decimal("0.5"):
        return "HALF"
    if fraction in {Decimal("0.25"), Decimal("0.75")}:
        return "QUARTER"
    return "OTHER"


def resolve_semantics(fields: dict[str, str]) -> tuple[dict[str, str], list[dict[str, Any]], list[str]]:
    """Resolve only closed-table exact semantics; never uses odds or row order."""
    result = dict(fields)
    audits: list[dict[str, Any]] = []
    reasons: list[str] = []
    family = result.get("FAMILY", "").strip().upper()
    market = result.get("MARKET", "").strip()
    market_key = " ".join(market.casefold().split())
    line = result.get("LINE", "").strip()

    kind = result.get("HANDICAP_KIND", "").strip().upper()
    taxonomy = result.get("HANDICAP_TAXONOMY", "").strip().upper()
    if family == "HANDICAP_EUROPEAN" and (not kind or not taxonomy):
        if "(2-drożny)" in market_key or "(2-way)" in market_key:
            result["HANDICAP_KIND"] = "TWO_WAY"
            result["HANDICAP_TAXONOMY"] = "TWO_WAY_NO_DRAW"
            audits.extend((
                _audit("HC_EUROPEAN_EXACT_2WAY_MARKET_V1", "HANDICAP_KIND", "TWO_WAY", {"FAMILY": family, "MARKET": market}, False),
                _audit("HC_EUROPEAN_EXACT_2WAY_MARKET_V1", "HANDICAP_TAXONOMY", "TWO_WAY_NO_DRAW", {"FAMILY": family, "MARKET": market}, False),
            ))
        elif market_key in {"handicap", "handicap 1. połowa", "handicap 2. połowa"}:
            result["HANDICAP_KIND"] = "THREE_WAY"
            result["HANDICAP_TAXONOMY"] = "EUROPEAN_THREE_WAY_WITH_DRAW"
            audits.extend((
                _audit("HC_EUROPEAN_EXACT_3WAY_MARKET_V1", "HANDICAP_KIND", "THREE_WAY", {"FAMILY": family, "MARKET": market}, False),
                _audit("HC_EUROPEAN_EXACT_3WAY_MARKET_V1", "HANDICAP_TAXONOMY", "EUROPEAN_THREE_WAY_WITH_DRAW", {"FAMILY": family, "MARKET": market}, False),
            ))
        else:
            reasons.append("HANDICAP_SEMANTICS_UNPROVEN")

    settlement = result.get("SETTLEMENT", "").strip().upper()
    if settlement and settlement != "UNKNOWN":
        if settlement not in KNOWN_SETTLEMENTS:
            reasons.append("SETTLEMENT_UNRECOGNIZED")
        else:
            result["SETTLEMENT"] = settlement
        return result, audits, reasons

    exact_fixed = {
        "1X2": ("SEM_1X2_WIN_LOSE_V1", "WIN_LOSE"),
        "BTTS": ("SEM_BTTS_WIN_LOSE_V1", "WIN_LOSE"),
        "DOUBLE_CHANCE": ("SEM_DOUBLE_CHANCE_WIN_LOSE_V1", "WIN_LOSE"),
        "DNB": ("SEM_DNB_PUSH_ON_DRAW_V1", "PUSH_ON_DRAW"),
        "CORRECT_SCORE": ("SEM_CORRECT_SCORE_WIN_LOSE_V1", "WIN_LOSE"),
    }
    if family in exact_fixed:
        rule_id, value = exact_fixed[family]
    elif family in {"GOALS_OU", "TEAM_TOTALS_HOME", "TEAM_TOTALS_AWAY"}:
        line_class = _line_class(line)
        table = {
            "HALF": ("SEM_TOTAL_HALF_NO_PUSH_V1", "NO_PUSH"),
            "INTEGER": ("SEM_TOTAL_INTEGER_PUSH_V1", "PUSH_POSSIBLE"),
            "QUARTER": ("SEM_TOTAL_QUARTER_ASIAN_SPLIT_V1", "ASIAN_SPLIT"),
        }
        if line_class not in table:
            reasons.append("TOTAL_LINE_SEMANTICS_UNPROVEN")
            return result, audits, reasons
        rule_id, value = table[line_class]
    elif family == "HANDICAP_EUROPEAN":
        kind = result.get("HANDICAP_KIND", "").strip().upper()
        line_class = _line_class(line)
        if kind == "THREE_WAY":
            rule_id, value = "SEM_EUROPEAN_3WAY_WIN_DRAW_LOSE_V1", "WIN_DRAW_LOSE"
        elif kind == "TWO_WAY" and line_class == "HALF":
            rule_id, value = "SEM_EUROPEAN_2WAY_HALF_NO_PUSH_V1", "NO_PUSH"
        elif kind == "TWO_WAY" and line_class == "INTEGER":
            rule_id, value = "SEM_EUROPEAN_2WAY_INTEGER_PUSH_V1", "PUSH_POSSIBLE"
        else:
            reasons.append("HANDICAP_SETTLEMENT_UNPROVEN")
            return result, audits, reasons
    else:
        reasons.append("SETTLEMENT_SEMANTICS_UNPROVEN")
        return result, audits, reasons

    result["SETTLEMENT"] = value
    audits.append(_audit(rule_id, "SETTLEMENT", value, {
        "FAMILY": family, "MARKET": market, "PERIOD": result.get("PERIOD", ""),
        "SELECTION": result.get("SELECTION", ""), "LINE": line,
        "HANDICAP_KIND": result.get("HANDICAP_KIND", ""),
        "HANDICAP_TAXONOMY": result.get("HANDICAP_TAXONOMY", ""),
    }, False))
    return result, audits, reasons


SEMANTIC_RULE_IDS = (
    "HC_EUROPEAN_EXACT_2WAY_MARKET_V1", "HC_EUROPEAN_EXACT_3WAY_MARKET_V1",
    "SEM_1X2_WIN_LOSE_V1", "SEM_BTTS_WIN_LOSE_V1", "SEM_DOUBLE_CHANCE_WIN_LOSE_V1",
    "SEM_DNB_PUSH_ON_DRAW_V1", "SEM_CORRECT_SCORE_WIN_LOSE_V1",
    "SEM_TOTAL_HALF_NO_PUSH_V1", "SEM_TOTAL_INTEGER_PUSH_V1", "SEM_TOTAL_QUARTER_ASIAN_SPLIT_V1",
    "SEM_EUROPEAN_3WAY_WIN_DRAW_LOSE_V1", "SEM_EUROPEAN_2WAY_HALF_NO_PUSH_V1",
    "SEM_EUROPEAN_2WAY_INTEGER_PUSH_V1",
)
