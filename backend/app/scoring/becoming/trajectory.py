"""到達予測(North Star)。snapshot の次元推定トレンドから ETA とボトルネックを出す。

純関数・DB非依存。snapshot は {date, dim_estimates: {dim: value}} の dict で受ける。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date


def dimension_slope(points: Sequence[tuple[date, float]]) -> float | None:
    """(date, value) 列から最小二乗の傾き(units/day)。2点未満は None。"""
    pts = sorted(points, key=lambda p: p[0])
    if len(pts) < 2:
        return None
    d0 = pts[0][0]
    xs = [(d - d0).days for d, _ in pts]
    ys = [v for _, v in pts]
    n = len(pts)
    sx, sy = sum(xs), sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys, strict=True))
    denom = n * sxx - sx * sx
    if denom == 0:
        return None
    return round((n * sxy - sx * sy) / denom, 6)


def project(
    snaps: Sequence[dict],
    targets: dict[str, float],
    weights: dict[str, float],
    window_days: int,
    min_snapshots: int,
) -> dict:
    """重み付き次元の傾きから ETA・ボトルネック・per-dimension を返す。"""
    dim_snaps = [s for s in snaps if s.get("dim_estimates")]
    confidence = "medium" if len(dim_snaps) >= min_snapshots else "low"
    latest_date = max((s["date"] for s in dim_snaps), default=None)

    weighted = [d for d in targets if weights.get(d, 0) > 0]
    per_dimension: list[dict] = []
    times: dict[str, float | None] = {}

    for d in weighted:
        points: list[tuple[date, float]] = []
        for s in dim_snaps:
            if latest_date is not None and (latest_date - s["date"]).days > window_days:
                continue
            v = s["dim_estimates"].get(d)
            if v is not None:
                points.append((s["date"], float(v)))
        slope = dimension_slope(points)
        current = points[-1][1] if points else None
        target = targets[d]
        if slope is not None and slope > 0 and current is not None:
            ttt = (target - current) / slope
            ttt = max(0, round(ttt))
        else:
            ttt = None
        times[d] = ttt
        per_dimension.append({
            "id": d, "current": current, "target": target,
            "slope_per_day": slope, "time_to_target_days": ttt,
        })

    bottleneck = None
    if weighted:
        bottleneck = max(
            weighted,
            key=lambda d: (float("inf") if times[d] is None else times[d], weights.get(d, 0)),
        )

    finite = [t for t in times.values() if t is not None]
    # 重み付き次元のどれかが到達不能(None)なら全体 ETA は出さない(プロフィール未到達)
    eta_days = max(finite) if finite and len(finite) == len(weighted) else None
    return {
        "eta_days": eta_days,
        "bottleneck_dimension": bottleneck,
        "confidence": confidence,
        "per_dimension": per_dimension,
    }
