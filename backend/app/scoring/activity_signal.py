"""活動/外出シグナル: 全ソース相互補完で「動いたか・外に出たか」を推測。

Garmin は着けない日があり iPhone も持たない瞬間がある。どの単一デバイスにも依存せず、
その日に存在する最良のソースから推測し、どのソースも無い日は『不明』(None) とする
(欠損をゼロにしない)。

- 歩数: daily_summary.steps と hae step_count 日合計の最大値 (合算は二重計上)。
- 距離: walking_running_distance + workout 距離。
- 外出: 屋外種別ワークアウト or 一定以上の距離。
- confidence: Garmin連続HR/屋外ワークアウト=high、iPhoneあり=medium、疎=low、皆無=none。

設計: docs/superpowers/specs/2026-06-23-activity-signal-multisource-design.md
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_type
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.config import get_settings
from app.db import session_scope
from app.models import DailySummary, MetricSample, Workout

OUTDOOR_TYPES = {
    "walking", "running", "hiking", "cycling", "rucking", "trail_running",
    "walk", "run", "road_biking", "mountain_biking", "open_water_swimming",
}
MOVE_STEPS = 1500          # これ以上 or 距離/ワークアウト/運動分 → 動いた
MOVE_DISTANCE_M = 800
OUTDOOR_DISTANCE_M = 1500  # 屋外ワークアウトが無くても、この距離なら外出とみなす


@dataclass(frozen=True)
class DayEvidence:
    date: date_type
    steps: float | None
    distance_m: float | None
    workouts: tuple[str, ...]
    outdoor_workout: bool
    exercise_min: float | None
    has_hr: bool
    sources: tuple[str, ...]


def classify(ev: DayEvidence) -> dict:
    """純粋関数。DayEvidence から moved/went_outside/confidence を判定。

    coverage (歩数/距離/ワークアウト/運動分/HR のいずれか) が無ければ全て None (不明)。
    """
    steps = ev.steps or 0
    dist = ev.distance_m or 0
    exer = ev.exercise_min or 0
    has_coverage = bool(
        ev.sources
        and (ev.steps is not None or ev.distance_m is not None or ev.workouts or ev.has_hr or ev.exercise_min is not None)
    )

    if not has_coverage:
        return {
            "date": ev.date.isoformat(),
            "moved": None,
            "went_outside": None,
            "confidence": "none",
            "steps": None,
            "distance_m": None,
            "sources": list(ev.sources),
        }

    moved = steps >= MOVE_STEPS or dist >= MOVE_DISTANCE_M or bool(ev.workouts) or exer > 0
    went_outside = ev.outdoor_workout or dist >= OUTDOOR_DISTANCE_M

    if "garmin" in ev.sources and (ev.has_hr or ev.outdoor_workout):
        confidence = "high"
    elif ev.steps is not None or ev.distance_m is not None or ev.workouts:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "date": ev.date.isoformat(),
        "moved": bool(moved),
        "went_outside": bool(went_outside),
        "confidence": confidence,
        "steps": round(steps) if ev.steps is not None else None,
        "distance_m": round(dist) if ev.distance_m is not None else None,
        "sources": list(ev.sources),
    }


def _sum_metric(session, day: date_type, source: str, key: str) -> float | None:
    """その日 (date(ts)) の指定ソース・指標の合計。無ければ None。"""
    total = session.execute(
        select(func.sum(MetricSample.value)).where(
            MetricSample.source == source,
            MetricSample.metric_key == key,
            func.date(MetricSample.ts) == day.isoformat(),
        )
    ).scalar()
    return float(total) if total is not None else None


def _has_hr(session, day: date_type) -> bool:
    row = session.execute(
        select(MetricSample.id).where(
            MetricSample.metric_key == "heart_rate_avg",
            func.date(MetricSample.ts) == day.isoformat(),
        ).limit(1)
    ).first()
    return row is not None


def gather_day(session, day: date_type) -> DayEvidence:
    """1日分の証跡を全ソースから集約する。"""
    sources: set[str] = set()

    # 歩数: daily_summary と hae step_count の最大 (二重計上回避)
    ds = session.get(DailySummary, day)
    ds_steps = float(ds.steps) if ds and ds.steps is not None else None
    hae_steps = _sum_metric(session, day, "hae", "step_count")
    step_vals = [s for s in (ds_steps, hae_steps) if s is not None]
    steps = max(step_vals) if step_vals else None
    if ds_steps is not None:
        sources.add("daily_summary")
    if hae_steps is not None:
        sources.add("hae")

    # 距離: hae walking_running_distance + workout 距離
    hae_dist = _sum_metric(session, day, "hae", "walking_running_distance")
    if hae_dist is not None:
        sources.add("hae")

    workout_rows = session.execute(
        select(Workout.type, Workout.distance_m, Workout.source).where(
            func.date(Workout.start) == day.isoformat()
        )
    ).all()
    workouts = tuple(str(w.type) for w in workout_rows if w.type)
    wo_dist = sum(float(w.distance_m) for w in workout_rows if w.distance_m is not None)
    outdoor = any((w.type or "").lower() in OUTDOOR_TYPES for w in workout_rows)
    for w in workout_rows:
        if w.source:
            sources.add(w.source)

    dist_vals = [d for d in (hae_dist, wo_dist if workout_rows else None) if d]
    distance_m = sum(dist_vals) if dist_vals else None

    # 運動分: hae apple_exercise_time + garmin intensity minutes
    exer_parts = [
        _sum_metric(session, day, "hae", "apple_exercise_time"),
        _sum_metric(session, day, "garmin", "intensity_minutes_moderate"),
        _sum_metric(session, day, "garmin", "intensity_minutes_vigorous"),
    ]
    exer_present = [e for e in exer_parts if e is not None]
    exercise_min = sum(exer_present) if exer_present else None
    if _sum_metric(session, day, "garmin", "intensity_minutes_moderate") is not None:
        sources.add("garmin")

    has_hr = _has_hr(session, day)
    if has_hr:
        # HR がどちらソースかは問わず、装着証跡として扱う (garmin 優先で confidence へ)
        if session.execute(
            select(MetricSample.id).where(
                MetricSample.source == "garmin",
                MetricSample.metric_key == "heart_rate_avg",
                func.date(MetricSample.ts) == day.isoformat(),
            ).limit(1)
        ).first() is not None:
            sources.add("garmin")

    return DayEvidence(
        date=day,
        steps=steps,
        distance_m=distance_m,
        workouts=workouts,
        outdoor_workout=outdoor,
        exercise_min=exercise_min,
        has_hr=has_hr,
        sources=tuple(sorted(sources)),
    )


def recent_signals(days: int = 14) -> list[dict]:
    """直近 days 日のシグナル (新しい日が先頭)。"""
    settings = get_settings()
    today = datetime.now(ZoneInfo(settings.app_tz)).date()
    out: list[dict] = []
    with session_scope() as session:
        for i in range(days):
            day = today - timedelta(days=i)
            out.append(classify(gather_day(session, day)))
    return out
