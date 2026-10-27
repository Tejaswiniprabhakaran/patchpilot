"""Statistics for comparing configurations (A4).

Every comparison in the report is *paired*: two configurations run on the same instances, so
what matters is the instances where exactly one of them succeeded. McNemar's test asks whether
those disagreements lean one way more than chance would allow. With the small numbers in this
project the exact (binomial) version is used rather than the chi-squared approximation.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

Z_95 = 1.959963984540054


@dataclass(frozen=True)
class Rate:
    """``k`` successes out of ``n`` trials, with a Wilson 95% confidence interval."""

    k: int
    n: int

    @property
    def value(self) -> float:
        return self.k / self.n if self.n else 0.0

    def interval(self, z: float = Z_95) -> tuple[float, float]:
        return wilson_interval(self.k, self.n, z)

    def describe(self) -> str:
        if not self.n:
            return "n/a"
        low, high = self.interval()
        return f"{self.k}/{self.n} ({self.value:.1%}, 95% CI {low:.1%}-{high:.1%})"


def wilson_interval(k: int, n: int, z: float = Z_95) -> tuple[float, float]:
    """Wilson score interval: well-behaved for small n and rates near 0 or 1."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return (max(0.0, centre - half), min(1.0, centre + half))


def mcnemar_exact(a_only: int, b_only: int) -> float:
    """Two-sided exact McNemar p-value from the two discordant counts.

    Under the null hypothesis each disagreement is equally likely to favour either side, so the
    smaller count follows Binomial(a_only + b_only, 0.5).
    """
    n = a_only + b_only
    if n == 0:
        return 1.0
    tail = math.ldexp(sum(math.comb(n, i) for i in range(min(a_only, b_only) + 1)), -n)
    return min(1.0, 2 * tail)


@dataclass(frozen=True)
class PairedComparison:
    a: str
    b: str
    n: int  # instances both configurations ran on
    both: int
    a_only: int
    b_only: int
    neither: int

    @property
    def p_value(self) -> float:
        return mcnemar_exact(self.a_only, self.b_only)

    def significant(self, alpha: float = 0.05) -> bool:
        return self.p_value < alpha

    def as_row(self) -> dict[str, Any]:
        return {
            "a": self.a,
            "b": self.b,
            "n": self.n,
            "a_resolved": self.both + self.a_only,
            "b_resolved": self.both + self.b_only,
            "both": self.both,
            "a_only": self.a_only,
            "b_only": self.b_only,
            "neither": self.neither,
            "mcnemar_exact_p": round(self.p_value, 4),
            "significant_at_0.05": self.significant(),
        }


def paired_compare(
    a_name: str, a: Mapping[str, bool], b_name: str, b: Mapping[str, bool]
) -> PairedComparison:
    """Compare two configurations on the instances both of them have results for."""
    common = sorted(set(a) & set(b))
    both = sum(1 for i in common if a[i] and b[i])
    a_only = sum(1 for i in common if a[i] and not b[i])
    b_only = sum(1 for i in common if b[i] and not a[i])
    return PairedComparison(
        a_name, b_name, len(common), both, a_only, b_only, len(common) - both - a_only - b_only
    )


def resolved_within(rows: Iterable[Mapping[str, Any]], k: int) -> Rate:
    """Resolution rate if the agent had been allowed at most ``k`` attempts.

    The agent stops at its first passing attempt, so a run resolved at attempt j <= k would have
    been resolved by a k-attempt run too (decisions D12: valid at temperature 0 and a fixed seed).
    """
    rows = list(rows)
    hits = sum(
        1
        for r in rows
        if r.get("resolved") and (r.get("best_attempt") or r.get("attempts_used") or 0) <= k
    )
    return Rate(hits, len(rows))


def describe_numbers(values: Iterable[float | None]) -> dict[str, float]:
    data = sorted(v for v in values if v is not None)
    if not data:
        return {"n": 0, "mean": 0.0, "median": 0.0}
    middle = len(data) // 2
    median = data[middle] if len(data) % 2 else (data[middle - 1] + data[middle]) / 2
    return {"n": len(data), "mean": round(sum(data) / len(data), 2), "median": round(median, 2)}
