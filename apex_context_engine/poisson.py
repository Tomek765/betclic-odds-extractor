from __future__ import annotations

import math


def poisson_pmf(k: int, lam: float) -> float:
    if k < 0 or lam < 0:
        return 0.0
    return math.exp(-lam) * (lam**k) / math.factorial(k)


def probability_at_least(n: int, lam: float) -> float:
    return 1.0 - sum(poisson_pmf(k, lam) for k in range(n))


def probability_total_over(line: float, lam: float) -> float:
    threshold = int(math.floor(line)) + 1
    return probability_at_least(threshold, lam)


def invert_over_probability(line: float, target: float) -> float:
    if not 0.0 < target < 1.0:
        raise ValueError("Target probability must be between 0 and 1")
    lo, hi = 0.0001, 12.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        value = probability_total_over(line, mid)
        if value < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def top_scores(home_lambda: float, away_lambda: float, limit: int = 6) -> list[dict]:
    rows: list[dict] = []
    for home in range(0, 8):
        for away in range(0, 8):
            prob = poisson_pmf(home, home_lambda) * poisson_pmf(away, away_lambda)
            rows.append({"score": f"{home}:{away}", "probability": prob})
    rows.sort(key=lambda item: item["probability"], reverse=True)
    return rows[:limit]
