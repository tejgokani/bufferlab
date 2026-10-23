"""Summary statistics for repeated runs.

The confidence interval is a two-sided 95% Student-t interval for the mean,
``mean +/- t(0.975, n-1) * s / sqrt(n)``.  It assumes replications are
independent (different seeds) and roughly normally distributed means.  It is a
description of sampling variability across replications, **not** a significance
test between algorithms.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

# t(0.975, df) for df = 1..30, then selected larger df.
_T975 = [
    12.706,
    4.303,
    3.182,
    2.776,
    2.571,
    2.447,
    2.365,
    2.306,
    2.262,
    2.228,
    2.201,
    2.179,
    2.160,
    2.145,
    2.131,
    2.120,
    2.110,
    2.101,
    2.093,
    2.086,
    2.080,
    2.074,
    2.069,
    2.064,
    2.060,
    2.056,
    2.052,
    2.048,
    2.045,
    2.042,
]
_T975_LARGE = [(40, 2.021), (60, 2.000), (120, 1.980)]


def t_critical_975(df: int) -> float:
    if df < 1:
        raise ValueError("degrees of freedom must be >= 1")
    if df <= 30:
        return _T975[df - 1]
    for bound, value in _T975_LARGE:
        if df <= bound:
            return value
    return 1.960


@dataclass(frozen=True)
class SummaryStats:
    n: int
    mean: float | None
    sd: float | None
    ci_low: float | None
    ci_high: float | None
    minimum: float | None
    maximum: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def half_width(self) -> float | None:
        if self.ci_low is None or self.ci_high is None or self.mean is None:
            return None
        return self.ci_high - self.mean


def summarize(values: list[float | None]) -> SummaryStats:
    xs = [float(v) for v in values if v is not None and not math.isnan(v)]
    n = len(xs)
    if n == 0:
        return SummaryStats(0, None, None, None, None, None, None)
    mean = sum(xs) / n
    if n == 1:
        return SummaryStats(1, mean, None, None, None, mean, mean)
    sd = math.sqrt(sum((x - mean) ** 2 for x in xs) / (n - 1))
    half = t_critical_975(n - 1) * sd / math.sqrt(n)
    return SummaryStats(n, mean, sd, mean - half, mean + half, min(xs), max(xs))
