from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Baseline:
    mean: float
    std: float
    n: int


def build_baseline(values: Iterable[float | None]) -> Baseline | None:
    arr = np.array(
        [float(v) for v in values if v is not None and not _is_nan(v)],
        dtype=float,
    )
    if arr.size == 0:
        return None
    mean = float(arr.mean())
    std = float(arr.std(ddof=0))
    if std == 0.0:
        std = 1e-6
    return Baseline(mean=mean, std=std, n=int(arr.size))


def ewma(values: list[float | None], span: int) -> float | None:
    cleaned = [float(v) for v in values if v is not None and not _is_nan(v)]
    if not cleaned:
        return None
    alpha = 2.0 / (span + 1)
    out = cleaned[0]
    for v in cleaned[1:]:
        out = alpha * v + (1 - alpha) * out
    return float(out)


def _is_nan(v: float) -> bool:
    try:
        return v != v  # NaN check
    except TypeError:
        return False
