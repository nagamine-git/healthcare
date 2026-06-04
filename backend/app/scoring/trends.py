"""日次スコア系列から前日比・前週比・トレンド方向を計算する DB 非依存の純粋関数群。

入力は ``(date, value)`` の系列。出力は JSON 化可能な dict。
DB アクセスは呼び出し側 (dashboard / llm) が担い、ここはロジックに専念する。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Literal

Direction = Literal["improving", "stable", "declining"]

# 傾きを系列レンジで正規化した値がこの閾値未満なら "stable" とみなす。
STABLE_THRESHOLD = 0.02


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _linear_slope(values: list[float]) -> float | None:
    """等間隔 x=0..n-1 に対する最小二乗法の傾き。2 点未満や分散ゼロは None。"""
    n = len(values)
    if n < 2:
        return None
    mean_x = (n - 1) / 2
    mean_y = sum(values) / n
    num = sum((i - mean_x) * (v - mean_y) for i, v in enumerate(values))
    den = sum((i - mean_x) ** 2 for i in range(n))
    if den == 0:
        return None
    return num / den


def _direction(values: list[float], higher_is_better: bool) -> Direction | None:
    slope = _linear_slope(values)
    if slope is None:
        return None
    rng = max(values) - min(values)
    norm = slope / rng if rng > 1e-9 else 0.0
    if not higher_is_better:
        norm = -norm
    if norm > STABLE_THRESHOLD:
        return "improving"
    if norm < -STABLE_THRESHOLD:
        return "declining"
    return "stable"


def _clean(series: list[tuple[date, float | None]]) -> list[tuple[date, float]]:
    """None を除外し日付昇順にそろえる。"""
    pts = [(d, v) for d, v in series if v is not None]
    pts.sort(key=lambda p: p[0])
    return pts


def compute_trend(
    series: list[tuple[date, float | None]],
    *,
    higher_is_better: bool = True,
    direction_window: int = 7,
) -> dict[str, Any]:
    """日次系列からトレンド指標を計算する。"""
    pts = _clean(series)
    values = [v for _, v in pts]

    current = values[-1] if values else None
    prev_day_change = values[-1] - values[-2] if len(values) >= 2 else None

    week_over_week: dict[str, Any] | None = None
    if len(values) >= 8:
        recent = _mean(values[-7:])
        prior = _mean(values[-14:-7])
        if recent is not None and prior is not None:
            delta = recent - prior
            pct = (delta / prior * 100) if prior != 0 else None
            week_over_week = {
                "delta": round(delta, 2),
                "pct": round(pct, 1) if pct is not None else None,
            }

    direction = (
        _direction(values[-direction_window:], higher_is_better)
        if len(values) >= 2
        else None
    )

    return {
        "current": round(current, 2) if current is not None else None,
        "prev_day_change": round(prev_day_change, 2)
        if prev_day_change is not None
        else None,
        "week_over_week": week_over_week,
        "direction": direction,
    }


def daily_series(series: list[tuple[date, float | None]]) -> list[dict[str, Any]]:
    return [{"date": d.isoformat(), "value": round(v, 2)} for d, v in _clean(series)]


def weekly_average(series: list[tuple[date, float | None]]) -> list[dict[str, Any]]:
    """カレンダー週 (月曜始め) ごとの平均。各点の date は週開始 (月曜)。"""
    buckets: dict[date, list[float]] = defaultdict(list)
    for d, v in _clean(series):
        monday = d - timedelta(days=d.weekday())
        buckets[monday].append(v)
    out: list[dict[str, Any]] = []
    for monday in sorted(buckets):
        vals = buckets[monday]
        out.append({"date": monday.isoformat(), "value": round(sum(vals) / len(vals), 2)})
    return out


def linear_regression_endpoints(
    series: list[tuple[date, float | None]],
) -> dict[str, Any] | None:
    """生値系列の線形回帰の両端2点を返す (グラフの点線用)。点が2未満なら None。"""
    pts = _clean(series)
    if len(pts) < 2:
        return None
    values = [v for _, v in pts]
    slope = _linear_slope(values)
    if slope is None:
        return None
    n = len(values)
    mean_y = sum(values) / n
    intercept = mean_y - slope * (n - 1) / 2  # x=0..n-1
    return {
        "start": {"date": pts[0][0].isoformat(), "value": round(intercept, 2)},
        "end": {"date": pts[-1][0].isoformat(), "value": round(intercept + slope * (n - 1), 2)},
    }
