"""「今日の流れ」タイムライン用の集約 API。

1日 (JST 0-24h) を 1 本の帯で見せるため、時刻を持つ全データを
JST の時 (float 0-24) に正規化して返す。クライアントはそのまま
SVG の x 座標にマップできる。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.db import session_scope
from app.models import (
    BodyBattery,
    CaffeineIntake,
    MetricSample,
    MigraineEpisode,
    SleepSession,
    SubjectiveCheckin,
    Workout,
)
from app.scoring.timewindow import app_today, jst_day_bounds

router = APIRouter()
JST = ZoneInfo("Asia/Tokyo")


def _hour(ts_naive_utc: datetime) -> float:
    """naive UTC → JST の時 (0-24 float)。"""
    dt = ts_naive_utc.replace(tzinfo=UTC).astimezone(JST)
    return round(dt.hour + dt.minute / 60 + dt.second / 3600, 2)


@router.get("/api/timeline")
async def day_timeline(date: str | None = Query(default=None)) -> dict[str, Any]:
    from datetime import date as date_type

    target = date_type.fromisoformat(date) if date else app_today()
    start, end = jst_day_bounds(target)
    out: dict[str, Any] = {"date": target.isoformat()}

    now_jst = datetime.now(JST)
    out["now_h"] = (
        round(now_jst.hour + now_jst.minute / 60, 2) if now_jst.date() == target else None
    )

    with session_scope() as session:
        bb = session.execute(
            select(BodyBattery.ts, BodyBattery.value)
            .where(BodyBattery.ts >= start, BodyBattery.ts < end)
            .order_by(BodyBattery.ts)
        ).all()
        out["body_battery"] = [{"h": _hour(t), "v": float(v)} for t, v in bb if v is not None]

        st = session.execute(
            select(MetricSample.ts, MetricSample.value)
            .where(
                MetricSample.metric_key == "stress",
                MetricSample.value >= 0,
                MetricSample.ts >= start,
                MetricSample.ts < end,
            )
            .order_by(MetricSample.ts)
        ).all()
        out["stress"] = [{"h": _hour(t), "v": float(v)} for t, v in st if v is not None]

        # 睡眠ブロック: 中点 ± 総睡眠/2 で近似 (開始が前日に食い込む場合は負値)
        total_min = session.execute(
            select(SleepSession.total_min).where(SleepSession.date == target)
        ).scalar()
        midpoint = session.execute(
            select(MetricSample.value).where(
                MetricSample.metric_key == "sleep_midpoint_hour",
                MetricSample.ts >= start,
                MetricSample.ts < end,
            )
        ).scalar()
        if total_min and midpoint is not None:
            half_h = float(total_min) / 120.0
            out["sleep"] = {
                "start_h": round(float(midpoint) - half_h, 2),
                "end_h": round(float(midpoint) + half_h, 2),
            }
        else:
            out["sleep"] = None

        workouts = session.execute(
            select(Workout.start, Workout.end, Workout.type, Workout.duration_s)
            .where(Workout.start >= start, Workout.start < end)
            .order_by(Workout.start)
        ).all()
        out["workouts"] = [
            {
                "start_h": _hour(s),
                "end_h": _hour(e) if e else round(_hour(s) + (dur or 1800) / 3600, 2),
                "type": ty,
            }
            for s, e, ty, dur in workouts
        ]

        caff = session.execute(
            select(CaffeineIntake.ts, CaffeineIntake.mg, CaffeineIntake.source)
            .where(CaffeineIntake.ts >= start, CaffeineIntake.ts < end)
            .order_by(CaffeineIntake.ts)
        ).all()
        out["caffeine"] = [
            {"h": _hour(t), "mg": float(mg), "source": src} for t, mg, src in caff
        ]

        episodes = session.execute(
            select(MigraineEpisode.started_at, MigraineEpisode.ended_at, MigraineEpisode.severity)
            .where(
                MigraineEpisode.started_at < end,
                (MigraineEpisode.ended_at.is_(None)) | (MigraineEpisode.ended_at >= start),
            )
        ).all()
        out["migraine"] = [
            {
                "start_h": _hour(s) if s >= start else 0.0,
                "end_h": (_hour(e) if e < end else 24.0) if e else None,
                "severity": sev,
            }
            for s, e, sev in episodes
        ]

        ck = session.get(SubjectiveCheckin, target)
        out["checkin"] = (
            {
                "h": _hour(ck.updated_at),
                "mood": ck.mood,
                "energy": ck.energy,
                "stress": ck.stress,
                "soreness": ck.soreness,
            }
            if ck and ck.updated_at
            else None
        )

    # カレンダー予定 (gcal 未設定なら空)。終日予定は除外
    events: list[dict[str, Any]] = []
    try:
        from app.integrations.gcal import list_events_for_date

        for e in list_events_for_date(target):
            s, en = e.get("start") or "", e.get("end") or ""
            if len(s) <= 10 or len(en) <= 10:  # date-only = 終日
                continue
            sd, ed = datetime.fromisoformat(s).astimezone(JST), datetime.fromisoformat(en).astimezone(JST)
            events.append(
                {
                    "start_h": round(sd.hour + sd.minute / 60, 2),
                    "end_h": round(ed.hour + ed.minute / 60, 2) if ed.date() == target else 24.0,
                    "title": e.get("summary") or "",
                }
            )
    except Exception:
        pass
    out["events"] = events
    return out


@router.get("/api/day-story")
async def day_story(date: str | None = Query(default=None)) -> dict[str, Any]:
    """取れる全データから「その時間に何をしていたか」を推定したセグメント。"""
    from datetime import date as date_type

    from app.scoring.day_story import build_day_story

    target = date_type.fromisoformat(date) if date else app_today()
    start, end = jst_day_bounds(target)

    now_jst = datetime.now(JST)
    now_h = round(now_jst.hour + now_jst.minute / 60, 2) if now_jst.date() == target else None

    def _series(key: str) -> list[tuple[float, float]]:
        with session_scope() as session:
            rows = session.execute(
                select(MetricSample.ts, MetricSample.value).where(
                    MetricSample.metric_key == key,
                    MetricSample.ts >= start,
                    MetricSample.ts < end,
                    MetricSample.value.isnot(None),
                )
            ).all()
        return [(_hour(t), float(v)) for t, v in rows]

    steps = _series("step_count")
    heart_rate = _series("heart_rate_avg")
    stress = _series("stress")

    with session_scope() as session:
        resting_hr = session.execute(
            select(MetricSample.value)
            .where(MetricSample.metric_key == "resting_heart_rate")
            .order_by(MetricSample.ts.desc())
            .limit(1)
        ).scalar()
        total_min = session.execute(
            select(SleepSession.total_min).where(SleepSession.date == target)
        ).scalar()
        midpoint = session.execute(
            select(MetricSample.value).where(
                MetricSample.metric_key == "sleep_midpoint_hour",
                MetricSample.ts >= start,
                MetricSample.ts < end,
            )
        ).scalar()
        sleep = (
            {
                "start_h": round(float(midpoint) - float(total_min) / 120.0, 2),
                "end_h": round(float(midpoint) + float(total_min) / 120.0, 2),
            }
            if total_min and midpoint is not None
            else None
        )
        workouts = [
            {
                "start_h": _hour(s),
                "end_h": _hour(e) if e else round(_hour(s) + (dur or 1800) / 3600, 2),
                "type": ty,
            }
            for s, e, ty, dur in session.execute(
                select(Workout.start, Workout.end, Workout.type, Workout.duration_s)
                .where(Workout.start >= start, Workout.start < end)
            ).all()
        ]

    # カレンダー予定 (timeline と同じく終日除外)
    events: list[dict[str, Any]] = []
    try:
        from app.integrations.gcal import list_events_for_date

        for e in list_events_for_date(target):
            s, en = e.get("start") or "", e.get("end") or ""
            if len(s) <= 10 or len(en) <= 10:
                continue
            sd, ed = datetime.fromisoformat(s).astimezone(JST), datetime.fromisoformat(en).astimezone(JST)
            events.append(
                {
                    "start_h": round(sd.hour + sd.minute / 60, 2),
                    "end_h": round(ed.hour + ed.minute / 60, 2) if ed.date() == target else 24.0,
                    "title": e.get("summary") or "予定",
                }
            )
    except Exception:
        pass

    story = build_day_story(
        now_h=now_h,
        sleep=sleep,
        workouts=workouts,
        events=events,
        steps=steps,
        heart_rate=heart_rate,
        stress=stress,
        resting_hr=float(resting_hr) if resting_hr is not None else None,
    )
    story["date"] = target.isoformat()
    story["now_h"] = now_h
    return story
