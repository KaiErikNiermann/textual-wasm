"""Small statistics over benchmark samples, from the standard library's `statistics`."""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from typing import Final

MINIMUM_POINTS: Final[int] = 2
"""Fewer samples than this have no spread and no slope."""


def median(samples: Sequence[float]) -> float | None:
    # A float always: Firefox's whole-millisecond timings arrive as ints, and an int is a
    # count to the report.
    return float(statistics.median(samples)) if samples else None


def p95(samples: Sequence[float]) -> float | None:
    """The 95th percentile, or the single sample when there is only one."""
    if len(samples) < MINIMUM_POINTS:
        return float(samples[0]) if samples else None
    return float(statistics.quantiles(samples, n=20, method="inclusive")[18])


def slope(values: Sequence[float]) -> float | None:
    """Least-squares growth per step: the leak rate of a series of readings."""
    if len(values) < MINIMUM_POINTS:
        return None
    return statistics.linear_regression(range(len(values)), values).slope
