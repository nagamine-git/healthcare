from __future__ import annotations

from datetime import UTC, datetime, timedelta
from datetime import date as date_type
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import session_scope
from app.logging import get_logger
from app.models import (
    BodyBatteryDaily,
    DailyScore,
    HrvDaily,
    SleepSession,
    WeightSample,
    Workout,
)
from app.scoring.baselines import Baseline, build_baseline, ewma
from app.scoring.composite import composite_score
from app.scoring.subscores import (
    body_battery_subscore,
    body_fat_subscore,
    hrv_subscore,
    sleep_subscore,
    training_load_subscore,
    weight_subscore,
)
from app.scoring.timewindow import jst_day_bounds, jst_window_start

logger = get_logger(__name__)


def _weights() -> dict[str, float]:
    s = get_settings()
    return {
        "sleep": s.score_weight_sleep,
        "hrv": s.score_weight_hrv,
        "bb": s.score_weight_bb,
        "load": s.score_weight_load,
        "weight": s.score_weight_weight,
        "body_fat": s.score_weight_body_fat,
    }


def _hrv_baseline(session: Session, target: date_type) -> Baseline | None:
    settings = get_settings()
    start = target - timedelta(days=settings.baseline_window_days)
    rows = session.execute(
        select(HrvDaily.last_night_avg)
        .where(HrvDaily.date >= start, HrvDaily.date < target)
        .order_by(HrvDaily.date)
    ).all()
    return build_baseline([r[0] for r in rows])


def _weight_baseline_and_recent(
    session: Session, target: date_type
) -> tuple[Baseline | None, float | None]:
    settings = get_settings()
    start = jst_window_start(settings.baseline_window_days, target)
    rows = session.execute(
        select(WeightSample.weight_kg, WeightSample.ts)
        .where(WeightSample.ts >= start)
        .order_by(WeightSample.ts)
    ).all()
    all_values = [r[0] for r in rows]
    baseline = build_baseline(all_values)

    seven_days_start = jst_window_start(7, target)
    recent_values = [r[0] for r in rows if r[1] >= seven_days_start]
    recent_median: float | None = None
    if recent_values:
        sorted_v = sorted(recent_values)
        n = len(sorted_v)
        recent_median = (
            sorted_v[n // 2] if n % 2 == 1 else (sorted_v[n // 2 - 1] + sorted_v[n // 2]) / 2
        )
    return baseline, recent_median


def _recent_body_fat(session: Session, target: date_type) -> float | None:
    """直近 7 日 (JST 暦) の体脂肪率の中央値を返す。"""
    seven_days_start = jst_window_start(7, target)
    _, end = jst_day_bounds(target)
    rows = session.execute(
        select(WeightSample.body_fat_pct)
        .where(
            WeightSample.ts >= seven_days_start,
            WeightSample.ts < end,
            WeightSample.body_fat_pct.is_not(None),
        )
        .order_by(WeightSample.ts)
    ).all()
    values = [r[0] for r in rows if r[0] is not None]
    if not values:
        return None
    sorted_v = sorted(values)
    n = len(sorted_v)
    return sorted_v[n // 2] if n % 2 == 1 else (sorted_v[n // 2 - 1] + sorted_v[n // 2]) / 2


def _workout_load(training_load: float | None, duration_s: int | None) -> float:
    """1 ワークアウトの負荷量。Garmin training_load が無ければ時間(分)で代替する。

    bodyload._load と同じ規約。在宅・自重トレは training_load が欠損しがちで、
    これを 0 にすると ACWR の急性負荷が過小評価され「負荷不足」と誤判定するため、
    分(= 1 分 1 負荷ユニット)で粗く代替する。
    """
    if training_load is not None and training_load > 0:
        return float(training_load)
    if duration_s:
        return duration_s / 60.0
    return 0.0


def _daily_loads(
    workouts: list[tuple[datetime, float | None, int | None]], target: date_type
) -> list[float]:
    """ワークアウトを JST 暦日で集計し、target を末尾とする直近42日の日次負荷系列を返す。

    休養日は 0、training_load 欠損は _workout_load で分代替する(0 にしない)。
    """
    from app.scoring.timewindow import JST

    by_day: dict[date_type, float] = {}
    for start_dt, load, dur in workouts:
        if start_dt is None:
            continue
        day = start_dt.replace(tzinfo=UTC).astimezone(JST).date()
        by_day[day] = by_day.get(day, 0.0) + _workout_load(load, dur)
    return [by_day.get(target - timedelta(days=i), 0.0) for i in reversed(range(42))]


def _acwr(series: list[float]) -> tuple[float | None, float | None]:
    """同一の日次系列に span=7/28 の EWMA をかけ、最新時点の (急性, 慢性) を返す。

    急性・慢性を別々のサブ系列で計算するのではなく、同一の連続系列に異なる時定数の
    指数平滑をかけて最新値の比をとるのが ACWR(EWMA 版)の標準形(Williams 2017)。
    """
    return ewma(series, span=7), ewma(series, span=28)


def _training_load(session: Session, target: date_type) -> tuple[float | None, float | None]:
    """Return (acute, chronic) EWMA training loads up to and including target (JST)."""
    start_chronic = jst_window_start(42, target)
    _, end = jst_day_bounds(target)

    rows = session.execute(
        select(Workout.start, Workout.training_load, Workout.duration_s)
        .where(Workout.start >= start_chronic, Workout.start < end)
        .order_by(Workout.start)
    ).all()
    return _acwr(_daily_loads(rows, target))


def recompute_for_date(target: date_type) -> dict[str, Any]:
    with session_scope() as session:
        sleep = session.get(SleepSession, target)
        hrv = session.get(HrvDaily, target)
        bb = session.get(BodyBatteryDaily, target)

        sleep_sub = (
            sleep_subscore(
                garmin_sleep_score=sleep.sleep_score,
                total_min=sleep.total_min,
                deep_min=sleep.deep_min,
                rem_min=sleep.rem_min,
                light_min=sleep.light_min,
                awake_min=sleep.awake_min,
            )
            if sleep
            else None
        )
        hrv_baseline = _hrv_baseline(session, target)
        hrv_sub = hrv_subscore(hrv.last_night_avg if hrv else None, hrv_baseline)
        bb_sub = body_battery_subscore(morning_value=bb.morning_value if bb else None)

        acute, chronic = _training_load(session, target)
        load_sub = training_load_subscore(acute=acute, chronic=chronic)

        weight_baseline, recent_median = _weight_baseline_and_recent(session, target)
        weight_sub = weight_subscore(recent_median=recent_median, baseline=weight_baseline)

        from app.scoring.profile import resolve_profile
        settings = get_settings()
        prof = resolve_profile()
        recent_bf = _recent_body_fat(session, target)
        body_fat_sub = body_fat_subscore(
            recent_value=recent_bf,
            target_pct=prof.target_body_fat_pct,
            tolerance_pct=prof.body_fat_tolerance_pct,
        )

        subs = {
            "sleep": sleep_sub,
            "hrv": hrv_sub,
            "bb": bb_sub,
            "load": load_sub,
            "weight": weight_sub,
            "body_fat": body_fat_sub,
        }
        total = composite_score(subs, _weights())

        score = session.get(DailyScore, target)
        now = datetime.now(UTC).replace(tzinfo=None)
        if score is None:
            score = DailyScore(date=target, version=settings.score_version, computed_at=now)
            session.add(score)
        score.sleep_sub = sleep_sub
        score.hrv_sub = hrv_sub
        score.bb_sub = bb_sub
        score.load_sub = load_sub
        score.weight_sub = weight_sub
        score.body_fat_sub = body_fat_sub
        score.total = total
        score.computed_at = now
        score.version = settings.score_version

        return {"subs": subs, "total": total}


async def recompute_today_job() -> dict[str, Any]:
    from app.scoring.timewindow import app_today

    return recompute_for_date(app_today())


async def refresh_baselines_job() -> dict[str, Any]:
    """Currently a no-op placeholder; baselines are computed on demand."""
    logger.info("baseline_refresh_noop")
    return {"status": "ok"}
