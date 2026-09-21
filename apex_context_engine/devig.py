from __future__ import annotations

import math
from collections.abc import Sequence


class DevigError(ValueError):
    pass


def implied_probabilities(odds: Sequence[float]) -> list[float]:
    if not odds or any(o <= 1.0 or not math.isfinite(o) for o in odds):
        raise DevigError("ODDS_MUST_BE_FINITE_AND_ABOVE_ONE")
    return [1.0 / o for o in odds]


def _normalized(values: Sequence[float]) -> list[float]:
    total = math.fsum(values)
    if total <= 0 or not math.isfinite(total):
        raise DevigError("INVALID_PROBABILITY_TOTAL")
    result = [value / total for value in values]
    result[-1] += 1.0 - math.fsum(result)
    if any(value <= 0 or value >= 1 for value in result) or abs(math.fsum(result) - 1.0) > 1e-12:
        raise DevigError("INVALID_FAIR_PROBABILITIES")
    return result


def multiplicative(odds: Sequence[float]) -> list[float]:
    return _normalized(implied_probabilities(odds))


def power(odds: Sequence[float]) -> list[float]:
    q = implied_probabilities(odds)
    if len(q) < 2:
        raise DevigError("POWER_REQUIRES_AT_LEAST_TWO_OUTCOMES")
    if abs(math.fsum(q) - 1.0) < 1e-14:
        return _normalized(q)
    lo, hi = 0.01, 100.0
    if math.fsum(x**lo for x in q) < 1.0 or math.fsum(x**hi for x in q) > 1.0:
        raise DevigError("POWER_ROOT_NOT_BRACKETED")
    for _ in range(240):
        mid = (lo + hi) / 2.0
        if math.fsum(x**mid for x in q) > 1.0:
            lo = mid
        else:
            hi = mid
    return _normalized([x ** ((lo + hi) / 2.0) for x in q])


def shin(odds: Sequence[float]) -> tuple[list[float], float]:
    q = implied_probabilities(odds)
    if len(q) != 3:
        raise DevigError("SHIN_REQUIRES_EXACTLY_THREE_OUTCOMES")
    total = math.fsum(q)
    if total <= 1.0:
        raise DevigError("SHIN_REQUIRES_POSITIVE_OVERROUND")

    def probabilities(z: float) -> list[float]:
        denominator = 2.0 * (1.0 - z)
        return [
            (math.sqrt(z * z + 4.0 * (1.0 - z) * (x * x / total)) - z) / denominator
            for x in q
        ]

    lo, hi = 0.0, 0.999999999
    f_lo = math.fsum(probabilities(lo)) - 1.0
    f_hi = math.fsum(probabilities(hi)) - 1.0
    if f_lo * f_hi > 0:
        raise DevigError("SHIN_ROOT_NOT_BRACKETED")
    for _ in range(240):
        mid = (lo + hi) / 2.0
        if math.fsum(probabilities(mid)) > 1.0:
            lo = mid
        else:
            hi = mid
    z = (lo + hi) / 2.0
    return _normalized(probabilities(z)), z


def devig(odds: Sequence[float], preferred: str) -> tuple[list[float], str, dict, list[str]]:
    warnings: list[str] = []
    try:
        if preferred == "SHIN":
            probs, z = shin(odds)
            return probs, "SHIN", {"z": round(z, 12)}, warnings
        probs = power(odds)
        return probs, "POWER", {}, warnings
    except DevigError as exc:
        probs = multiplicative(odds)
        warnings.append(f"DEVIG_FALLBACK_MULTIPLICATIVE:{preferred}:{exc}")
        return probs, "MULTIPLICATIVE_FALLBACK", {"preferred": preferred, "reason": str(exc)}, warnings
