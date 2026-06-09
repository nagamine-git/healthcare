"""Debug 用エンドポイント。各データソースから取得したローデータを確認するため。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import desc, func, select

from app.db import session_scope
from app.models import (
    BodyBattery,
    BodyBatteryDaily,
    DailyScore,
    DailySummary,
    HrvDaily,
    LlmComment,
    MetricSample,
    SleepSession,
    SourceSync,
    WeightSample,
    Workout,
)
from app.scoring.timewindow import app_today

router = APIRouter()


def _to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


@router.get("/api/debug/sources")
async def debug_sources(
    days: int = Query(default=14, ge=1, le=365),
    metric_limit: int = Query(default=10, ge=1, le=200),
) -> dict[str, Any]:
    today = app_today()
    since_date = today - timedelta(days=days)
    since_dt = datetime.combine(since_date, datetime.min.time())

    with session_scope() as session:
        # Source sync
        syncs = session.execute(select(SourceSync)).scalars().all()
        sync_dict = {
            r.source: {
                "last_synced_at": _to_iso(r.last_synced_at),
                "last_error": r.last_error,
            }
            for r in syncs
        }

        # Sleep
        sleeps = session.execute(
            select(SleepSession)
            .where(SleepSession.date >= since_date)
            .order_by(desc(SleepSession.date))
        ).scalars().all()
        sleep_rows = [
            {
                "date": r.date.isoformat(),
                "source": r.source,
                "total_min": r.total_min,
                "deep_min": r.deep_min,
                "rem_min": r.rem_min,
                "light_min": r.light_min,
                "awake_min": r.awake_min,
                "sleep_score": r.sleep_score,
                "hrv_overnight_avg": r.hrv_overnight_avg,
            }
            for r in sleeps
        ]

        # HRV
        hrvs = session.execute(
            select(HrvDaily)
            .where(HrvDaily.date >= since_date)
            .order_by(desc(HrvDaily.date))
        ).scalars().all()
        hrv_rows = [
            {
                "date": r.date.isoformat(),
                "last_night_avg": r.last_night_avg,
                "weekly_avg": r.weekly_avg,
                "status": r.status,
            }
            for r in hrvs
        ]

        # Body Battery (latest 100)
        bb_samples = session.execute(
            select(BodyBattery).order_by(desc(BodyBattery.ts)).limit(100)
        ).scalars().all()
        bb_rows = [{"ts": _to_iso(r.ts), "value": r.value} for r in bb_samples]

        bb_daily = session.execute(
            select(BodyBatteryDaily)
            .where(BodyBatteryDaily.date >= since_date)
            .order_by(desc(BodyBatteryDaily.date))
        ).scalars().all()
        bb_daily_rows = [
            {
                "date": r.date.isoformat(),
                "max": r.max_value,
                "min": r.min_value,
                "morning": r.morning_value,
                "end_of_day": r.end_of_day,
            }
            for r in bb_daily
        ]

        # Workouts
        workouts = session.execute(
            select(Workout)
            .where(Workout.start >= since_dt)
            .order_by(desc(Workout.start))
        ).scalars().all()
        workout_rows = [
            {
                "id": r.id,
                "source": r.source,
                "start": _to_iso(r.start),
                "end": _to_iso(r.end),
                "type": r.type,
                "duration_s": r.duration_s,
                "distance_m": r.distance_m,
                "kcal": r.kcal,
                "training_load": r.training_load,
                "avg_hr": r.avg_hr,
                "max_hr": r.max_hr,
            }
            for r in workouts
        ]

        # Daily summary
        summaries = session.execute(
            select(DailySummary)
            .where(DailySummary.date >= since_date)
            .order_by(desc(DailySummary.date))
        ).scalars().all()
        summary_rows = [
            {
                "date": r.date.isoformat(),
                "steps": r.steps,
                "active_kcal": r.active_kcal,
                "resting_hr": r.resting_hr,
                "vo2max": r.vo2max,
                "training_status": r.training_status,
            }
            for r in summaries
        ]

        # Weight
        weights = session.execute(
            select(WeightSample)
            .where(WeightSample.ts >= since_dt)
            .order_by(desc(WeightSample.ts))
        ).scalars().all()
        weight_rows = [
            {
                "ts": _to_iso(r.ts),
                "weight_kg": r.weight_kg,
                "body_fat_pct": r.body_fat_pct,
                "muscle_kg": r.muscle_kg,
                "source": r.source,
            }
            for r in weights
        ]

        # Daily scores
        scores = session.execute(
            select(DailyScore)
            .where(DailyScore.date >= since_date)
            .order_by(desc(DailyScore.date))
        ).scalars().all()
        score_rows = [
            {
                "date": r.date.isoformat(),
                "total": r.total,
                "sleep": r.sleep_sub,
                "hrv": r.hrv_sub,
                "body_battery": r.bb_sub,
                "load": r.load_sub,
                "weight": r.weight_sub,
                "body_fat": r.body_fat_sub,
                "computed_at": _to_iso(r.computed_at),
                "version": r.version,
            }
            for r in scores
        ]

        # MetricSample: per-key counts + samples (recent)
        key_counts = session.execute(
            select(
                MetricSample.source,
                MetricSample.metric_key,
                func.count().label("n"),
                func.max(MetricSample.ts).label("latest"),
            )
            .where(MetricSample.ts >= since_dt)
            .group_by(MetricSample.source, MetricSample.metric_key)
            .order_by(desc("n"))
        ).all()
        metric_summary = [
            {"source": s, "metric_key": k, "count": n, "latest": _to_iso(latest)}
            for s, k, n, latest in key_counts
        ]
        metric_recent = []
        recent = session.execute(
            select(MetricSample)
            .where(MetricSample.ts >= since_dt)
            .order_by(desc(MetricSample.ts))
            .limit(metric_limit)
        ).scalars().all()
        for r in recent:
            metric_recent.append(
                {
                    "ts": _to_iso(r.ts),
                    "source": r.source,
                    "metric_key": r.metric_key,
                    "value": r.value,
                    "unit": r.unit,
                }
            )

        # LLM comments (latest 5)
        comments = session.execute(
            select(LlmComment).order_by(desc(LlmComment.generated_at)).limit(5)
        ).scalars().all()
        comment_rows = [
            {
                "date": r.date.isoformat(),
                "generated_at": _to_iso(r.generated_at),
                "model": r.model,
                "comment": r.comment,
                "payload": r.payload,
            }
            for r in comments
        ]

        return {
            "window_days": days,
            "sync": sync_dict,
            "sleep": sleep_rows,
            "hrv": hrv_rows,
            "body_battery_daily": bb_daily_rows,
            "body_battery_samples": bb_rows,
            "workouts": workout_rows,
            "daily_summary": summary_rows,
            "weights": weight_rows,
            "daily_score": score_rows,
            "metric_summary": metric_summary,
            "metric_recent": metric_recent,
            "llm_comments": comment_rows,
        }
