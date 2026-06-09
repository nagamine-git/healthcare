"""日次の主観チェックイン (気分/活力/ストレス/筋肉痛) の記録・取得 API。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import get_settings
from app.db import session_scope
from app.models import SubjectiveCheckin

router = APIRouter()


def _today() -> Any:
    return datetime.now(ZoneInfo(get_settings().app_tz)).date()


def _to_dict(row: SubjectiveCheckin) -> dict[str, Any]:
    return {
        "date": row.date.isoformat(),
        "mood": row.mood,
        "energy": row.energy,
        "stress": row.stress,
        "soreness": row.soreness,
        "note": row.note,
    }


_FIELDS = ("mood", "energy", "stress", "soreness")


class CheckinIn(BaseModel):
    mood: int | None = Field(default=None, ge=1, le=5)
    energy: int | None = Field(default=None, ge=1, le=5)
    stress: int | None = Field(default=None, ge=1, le=5)
    soreness: int | None = Field(default=None, ge=1, le=5)
    note: str | None = Field(default=None, max_length=500)
    clear: list[str] = Field(default_factory=list)  # null に戻すフィールド名
    date: str | None = None


@router.post("/api/checkin")
async def post_checkin(body: CheckinIn) -> dict[str, Any]:
    from datetime import date as date_type

    target = date_type.fromisoformat(body.date) if body.date else _today()
    with session_scope() as session:
        row = session.get(SubjectiveCheckin, target)
        if row is None:
            row = SubjectiveCheckin(date=target)
            session.add(row)
        # 指定されたフィールドだけ更新 (部分更新)
        for field in (*_FIELDS, "note"):
            val = getattr(body, field)
            if val is not None:
                setattr(row, field, val)
        # クリア指定は None に戻す
        for field in body.clear:
            if field in (*_FIELDS, "note"):
                setattr(row, field, None)
        row.updated_at = datetime.now(UTC).replace(tzinfo=None)
    return await get_checkin()


@router.get("/api/checkin")
async def get_checkin(days: int = 14) -> dict[str, Any]:
    today = _today()
    since = today - timedelta(days=days)
    with session_scope() as session:
        rows = session.execute(
            select(SubjectiveCheckin)
            .where(SubjectiveCheckin.date >= since)
            .order_by(SubjectiveCheckin.date.desc())
        ).scalars().all()
        items = [_to_dict(r) for r in rows]
        today_row = next((it for it in items if it["date"] == today.isoformat()), None)

    # サジェスト (淡色表示用): まず客観指標からの推定、欠けたら自己平均で補完。
    objective = _objective_suggestions(today)
    prior = [it for it in items if it["date"] != today.isoformat()]
    suggested: dict[str, int | None] = {}
    for f in _FIELDS:
        if objective.get(f) is not None:
            suggested[f] = objective[f]
            continue
        vals = [it[f] for it in prior if it[f] is not None]
        suggested[f] = round(sum(vals) / len(vals)) if vals else None
    return {"today": today_row, "items": items, "suggested": suggested}


def _objective_suggestions(target: Any) -> dict[str, int | None]:
    """当日の客観指標 (BB / ストレス / 睡眠 / トレ負荷) から主観の目安を推定。"""
    from sqlalchemy import func

    from app.models import BodyBattery, MetricSample, SleepSession, Workout
    from app.scoring.checkin_suggest import estimate_subjective
    from app.scoring.timewindow import jst_day_bounds

    start, end = jst_day_bounds(target)
    with session_scope() as session:
        bb = session.execute(
            select(BodyBattery.value).order_by(BodyBattery.ts.desc()).limit(1)
        ).scalar()
        stress_avg = session.execute(
            select(func.avg(MetricSample.value)).where(
                MetricSample.metric_key == "stress",
                MetricSample.value >= 0,
                MetricSample.ts >= start,
                MetricSample.ts < end,
            )
        ).scalar()
        # スカラーで取得 (セッション外参照による DetachedInstanceError を避ける)
        sleep_score = session.execute(
            select(SleepSession.sleep_score).where(SleepSession.date == target)
        ).scalar()
        load_48h = session.execute(
            select(func.sum(Workout.training_load)).where(
                Workout.start >= start - timedelta(hours=24),
                Workout.start < end,
            )
        ).scalar()
    return estimate_subjective(
        body_battery=float(bb) if bb is not None else None,
        stress_avg=float(stress_avg) if stress_avg is not None else None,
        sleep_score=float(sleep_score) if sleep_score is not None else None,
        training_load_48h=float(load_48h) if load_48h is not None else None,
    )
