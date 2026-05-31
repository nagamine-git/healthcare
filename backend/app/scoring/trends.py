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

# daily_score テーブルの取得列順 (エンドポイント / LLM が同順で SELECT する)。
SCORE_COLUMNS: list[str] = [
    "total",
    "sleep_sub",
    "hrv_sub",
    "bb_sub",
    "load_sub",
    "weight_sub",
    "body_fat_sub",
]

# API レスポンスキー / 表示ラベル / daily_score の列名。
TREND_METRICS: list[tuple[str, str, str]] = [
    ("total", "総合スコア", "total"),
    ("sleep", "睡眠", "sleep_sub"),
    ("hrv", "自律神経", "hrv_sub"),
    ("body_battery", "エネルギー", "bb_sub"),
    ("load", "運動負荷", "load_sub"),
    ("weight", "体重", "weight_sub"),
    ("body_fat", "体脂肪率", "body_fat_sub"),
]


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


def series_by_column(
    rows: list[tuple[Any, ...]],
) -> dict[str, list[tuple[date, float]]]:
    """``(date, *SCORE_COLUMNS)`` の行列を列ごとの (date, value) 系列に展開する。"""
    by_col: dict[str, list[tuple[date, float]]] = {c: [] for c in SCORE_COLUMNS}
    for row in rows:
        d = row[0]
        for offset, col in enumerate(SCORE_COLUMNS, start=1):
            v = row[offset]
            if v is not None:
                by_col[col].append((d, v))
    return by_col


def build_metrics(
    by_col: dict[str, list[tuple[date, float]]],
    *,
    granularity: str = "daily",
) -> dict[str, Any]:
    """列系列から API レスポンス用の metrics dict を組む。全指標 higher_is_better=True。"""
    metrics: dict[str, Any] = {}
    for key, label, col in TREND_METRICS:
        series = by_col.get(col, [])
        trend = compute_trend(series, higher_is_better=True)
        trend["series"] = (
            weekly_average(series) if granularity == "weekly" else daily_series(series)
        )
        metrics[key] = {"label": label, "higher_is_better": True, **trend}
    return metrics
