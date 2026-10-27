"""Robust statistics for benchmark iterations.

Rules (documented in docs/methodology.md):
- The score uses the median of the valid iterations.
- With 5 or more iterations, an iteration is an outlier when it is more than
  OUTLIER_K scaled MADs from the median. Outliers stay in the raw data but
  are excluded.
- A test is invalid when fewer than min_valid iterations remain, or when the
  coefficient of variation of the remaining iterations exceeds MAX_CV.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

OUTLIER_K = 3.0
MAD_SCALE = 1.4826  # makes MAD consistent with the standard deviation for normal data
MAX_CV = 0.10
MIN_FOR_OUTLIERS = 5
# Very steady tests (CV well under 1%) give a tiny MAD; a run is only an outlier
# if it is also this far from the median, so normal jitter is never rejected.
MIN_OUTLIER_DEVIATION = 0.02
SLOWDOWN_THRESHOLD = 0.05  # 5% slower from first to last half suggests throttling


def median(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("median of empty sequence")
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2:
        return float(s[mid])
    return (s[mid - 1] + s[mid]) / 2.0


def mad(values: Sequence[float]) -> float:
    m = median(values)
    return median([abs(v - m) for v in values])


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def stdev(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = mean(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / (len(values) - 1))


def coefficient_of_variation(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = mean(values)
    return stdev(values) / m if m else 0.0


def outlier_indices(values: Sequence[float], k: float = OUTLIER_K) -> List[int]:
    """Indices of values more than k scaled MADs from the median.

    With fewer than 5 values there is not enough data to call anything an
    outlier (with 3, MAD equals the smaller deviation and almost any run would
    be rejected), so short runs rely on the spread check alone.
    When MAD is zero (most values identical) any value that differs from the
    median by more than 1% is treated as an outlier.
    """
    if len(values) < MIN_FOR_OUTLIERS:
        return []
    m = median(values)
    spread = mad(values) * MAD_SCALE
    out = []
    for i, v in enumerate(values):
        if spread == 0:
            if m and abs(v - m) / m > 0.01:
                out.append(i)
        elif abs(v - m) > k * spread and (not m or abs(v - m) / abs(m) > MIN_OUTLIER_DEVIATION):
            out.append(i)
    return out


def slowdown_ratio(values: Sequence[float]) -> Optional[float]:
    """Mean of the second half divided by mean of the first half, minus 1.

    Positive values mean later iterations were slower (a throttling hint).
    """
    if len(values) < 4:
        return None
    half = len(values) // 2
    first, last = values[:half], values[-half:]
    return mean(last) / mean(first) - 1.0


@dataclass
class Summary:
    n_total: int
    n_valid: int
    median: Optional[float]
    mad: Optional[float]
    cv: Optional[float]
    min: Optional[float]
    max: Optional[float]
    outliers: List[int] = field(default_factory=list)
    slowdown: Optional[float] = None
    valid: bool = False
    reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "n_total": self.n_total,
            "n_valid": self.n_valid,
            "median": self.median,
            "mad": self.mad,
            "cv": self.cv,
            "min": self.min,
            "max": self.max,
            "outliers": self.outliers,
            "slowdown": self.slowdown,
            "valid": self.valid,
            "reason": self.reason,
        }


def summarize(values: Sequence[float], min_valid: int = 3, max_cv: float = MAX_CV) -> Summary:
    values = [float(v) for v in values]
    if not values:
        return Summary(0, 0, None, None, None, None, None, valid=False, reason="no measurements")
    outs = outlier_indices(values)
    kept = [v for i, v in enumerate(values) if i not in outs]
    cv = coefficient_of_variation(kept)
    s = Summary(
        n_total=len(values),
        n_valid=len(kept),
        median=median(kept),
        mad=mad(kept),
        cv=cv,
        min=min(kept),
        max=max(kept),
        outliers=outs,
        slowdown=slowdown_ratio(values),
    )
    if len(kept) < min_valid:
        s.reason = f"only {len(kept)} valid iterations (need {min_valid})"
    elif cv > max_cv:
        s.reason = f"spread too high (CV {cv:.1%} > {max_cv:.0%})"
    else:
        s.valid = True
    return s
