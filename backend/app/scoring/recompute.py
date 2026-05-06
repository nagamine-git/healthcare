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
    start = datetime.combine(target - timedelta(days=settings.baseline_window_days), datetime.min.time())
    rows = session.execute(
        select(WeightSample.weight_kg, WeightSample.ts)
        .where(WeightSample.ts >= start)
        .order_by(WeightSample.ts)
    ).all()
    all_values = [r[0] for r in rows]
    baseline = build_baseline(all_values)

    seven_days_start = datetime.combine(target - timedelta(days=7), datetime.min.time())
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
    """直近 7 日の体脂肪率の中央値を返す。"""
    seven_days_start = datetime.combine(target - timedelta(days=7), datetime.min.time())
    end = datetime.combine(target + timedelta(days=1), datetime.min.time())
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


def _training_load(session: Session, target: date_type) -> tuple[float | None, float | None]:
    """Return (acute, chronic) EWMA training loads up to and including target."""
    start_chronic = datetime.combine(target - timedelta(days=42), datetime.min.time())
    end = datetime.combine(target + timedelta(days=1), datetime.min.time())

    rows = session.execute(
        select(Workout.start, Workout.training_load)
        .where(Workout.start >= start_chronic, Workout.start < end)
        .order_by(Workout.start)
    ).all()

    by_day: dict[date_type, float] = {}
    for start_dt, load in rows:
        if load is None:
            continue
        day = start_dt.date()
        by_day[day] = by_day.get(day, 0.0) + float(load)

    def _series(days: int) -> list[float]:
        return [by_day.get(target - timedelta(days=i), 0.0) for i in reversed(range(days))]

    acute = ewma(_series(7), span=7)
    chronic = ewma(_series(28), span=28)
    return acute, chronic


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

        settings = get_settings()
        recent_bf = _recent_body_fat(session, target)
        body_fat_sub = body_fat_subscore(
            recent_value=recent_bf,
            target_pct=settings.target_body_fat_pct,
            tolerance_pct=settings.body_fat_tolerance_pct,
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
    target = datetime.now().date()
    return recompute_for_date(target)


async def refresh_baselines_job() -> dict[str, Any]:
    """Currently a no-op placeholder; baselines are computed on demand."""
    logger.info("baseline_refresh_noop")
    return {"status": "ok"}
