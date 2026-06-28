from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

# HRV (rMSSD) 用の最小 baseline 標本数。これ未満では std/log-std の推定が不安定で
# z が無意味になるため、HRV サブスコアを出さない(臨床的小標本ガード)。
HRV_MIN_BASELINE_N = 3


@dataclass(frozen=True)
class Baseline:
    mean: float
    std: float
    n: int
    # 対数空間の平均/標準偏差。rMSSD など対数正規分布の指標で log-z を取るために使う。
    # 全値が正のときのみ算出され、それ以外は None(線形 z にフォールバック)。
    log_mean: float | None = None
    log_std: float | None = None


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
    log_mean: float | None = None
    log_std: float | None = None
    if np.all(arr > 0.0):
        log_arr = np.log(arr)
        log_mean = float(log_arr.mean())
        log_std = float(log_arr.std(ddof=0))
        if log_std == 0.0:
            log_std = 1e-6
    return Baseline(
        mean=mean, std=std, n=int(arr.size), log_mean=log_mean, log_std=log_std
    )


def hrv_log_z(value: float | None, baseline: Baseline | None) -> float | None:
    """rMSSD は対数正規分布 (Nunan 2010, Plews 2013) のため log 空間で z を取る。

    線形 z より低 HRV(疲労)側の感度が上がる。log 統計が未算出(値が非正・古い
    Baseline)のときは線形 z にフォールバック。標本数が小さすぎる baseline は
    z が不安定なため None を返し、サブスコアから除外させる。返り値は [-2, 2] に clamp。
    """
    if value is None or baseline is None:
        return None
    if baseline.n < HRV_MIN_BASELINE_N:
        return None
    if (
        baseline.log_mean is not None
        and baseline.log_std is not None
        and float(value) > 0.0
    ):
        z = (math.log(float(value)) - baseline.log_mean) / baseline.log_std
    else:
        z = (float(value) - baseline.mean) / baseline.std
    return max(-2.0, min(2.0, z))


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
