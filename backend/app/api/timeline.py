"""「今日の流れ」タイムライン用の集約 API。

時刻を持つ全データを 1 本の帯 (横軸 0-span 時間) に正規化して返す。
ウィンドウは 2 種類:
  - window=day  : JST 暦日 (00:00-24:00)。日付指定可。
  - window=24h  : 直近 24 時間 (日付をまたぐ。深夜でも空にならない)。
クライアントは offset(0-span) をそのまま SVG の x にマップできる。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
SPAN_H = 24.0


def _resolve_window(window: str, date: str | None):
    """(origin_utc_naive, start_utc, end_utc, now_off, date_label, origin_jst) を返す。

    offset = (ts_utc - origin_utc) 時間。x 軸は常に 0..SPAN_H。
    """
    from datetime import date as date_type

    now_jst = datetime.now(JST)
    if window == "24h":
        end_jst = now_jst
        origin_jst = end_jst - timedelta(hours=SPAN_H)
        start_utc = origin_jst.astimezone(UTC).replace(tzinfo=None)
        end_utc = end_jst.astimezone(UTC).replace(tzinfo=None)
        return start_utc, start_utc, end_utc, SPAN_H, None, origin_jst
    # 暦日
    target = date_type.fromisoformat(date) if date else app_today()
    start_utc, end_utc = jst_day_bounds(target)
    origin_jst = datetime(target.year, target.month, target.day, tzinfo=JST)
    now_off = (now_jst.astimezone(UTC).replace(tzinfo=None) - start_utc).total_seconds() / 3600
    now_off = round(now_off, 2) if 0 <= now_off <= SPAN_H else None
    return start_utc, start_utc, end_utc, now_off, target.isoformat(), origin_jst


def _offsetter(origin_utc: datetime):
    def off(ts_naive_utc: datetime) -> float:
        h = (ts_naive_utc - origin_utc).total_seconds() / 3600
        return round(max(0.0, min(SPAN_H, h)), 2)
    return off


def _sleep_blocks(session, start_utc, end_utc, off) -> list[dict[str, float]]:
    """ウィンドウに重なる睡眠ブロックを絶対時刻で復元して offset 化。

    睡眠は (date, midpoint_hour, total_min) から絶対時刻を組み立てる。
    midpoint は date の早朝 (0-9時想定) に属するものとして date 00:00 + midpoint。
    """
    # ウィンドウが触れる JST 日付 ± 1 を候補に
    start_jst = start_utc.replace(tzinfo=UTC).astimezone(JST).date()
    end_jst = end_utc.replace(tzinfo=UTC).astimezone(JST).date()
    cand = {start_jst, end_jst, start_jst + timedelta(days=1)}
    blocks: list[dict[str, float]] = []
    for d in sorted(cand):
        total_min = session.execute(
            select(SleepSession.total_min).where(SleepSession.date == d)
        ).scalar()
        d_start, d_end = jst_day_bounds(d)
        midpoint = session.execute(
            select(MetricSample.value).where(
                MetricSample.metric_key == "sleep_midpoint_hour",
                MetricSample.ts >= d_start,
                MetricSample.ts < d_end,
            )
        ).scalar()
        if not total_min or midpoint is None:
            continue
        mid_jst = datetime(d.year, d.month, d.day, tzinfo=JST) + timedelta(hours=float(midpoint))
        half = timedelta(minutes=float(total_min) / 2)
        s_utc = (mid_jst - half).astimezone(UTC).replace(tzinfo=None)
        e_utc = (mid_jst + half).astimezone(UTC).replace(tzinfo=None)
        if e_utc <= start_utc or s_utc >= end_utc:
            continue
        blocks.append({"start_h": off(s_utc), "end_h": off(e_utc)})
    return blocks


def _gather(start_utc, end_utc, off) -> dict[str, Any]:
    """ウィンドウ内の全シリーズを offset 化して返す (両エンドポイント共通)。"""
    out: dict[str, Any] = {}
    with session_scope() as session:
        bb = session.execute(
            select(BodyBattery.ts, BodyBattery.value)
            .where(BodyBattery.ts >= start_utc, BodyBattery.ts < end_utc, BodyBattery.value.isnot(None))
            .order_by(BodyBattery.ts)
        ).all()
        out["body_battery"] = [{"h": off(t), "v": float(v)} for t, v in bb]

        def metric(key: str):
            return session.execute(
                select(MetricSample.ts, MetricSample.value).where(
                    MetricSample.metric_key == key,
                    MetricSample.value >= 0,
                    MetricSample.ts >= start_utc,
                    MetricSample.ts < end_utc,
                ).order_by(MetricSample.ts)
            ).all()

        out["stress"] = [{"h": off(t), "v": float(v)} for t, v in metric("stress")]
        out["_steps"] = [(off(t), float(v)) for t, v in metric("step_count")]
        hr_pairs = [(off(t), float(v)) for t, v in metric("heart_rate_avg")]
        out["_hr"] = hr_pairs
        out["heart_rate"] = [{"h": h, "v": v} for h, v in hr_pairs]
        out["_energy"] = [(off(t), float(v)) for t, v in metric("active_energy")]

        out["sleep_blocks"] = _sleep_blocks(session, start_utc, end_utc, off)

        wk = session.execute(
            select(Workout.start, Workout.end, Workout.type, Workout.duration_s)
            .where(Workout.start >= start_utc, Workout.start < end_utc).order_by(Workout.start)
        ).all()
        out["workouts"] = [
            {"start_h": off(s), "end_h": off(e) if e else off(s + timedelta(seconds=dur or 1800)),
             "type": ty}
            for s, e, ty, dur in wk
        ]

        caff = session.execute(
            select(CaffeineIntake.ts, CaffeineIntake.mg, CaffeineIntake.source)
            .where(CaffeineIntake.ts >= start_utc, CaffeineIntake.ts < end_utc).order_by(CaffeineIntake.ts)
        ).all()
        out["caffeine"] = [{"h": off(t), "mg": float(mg), "source": src} for t, mg, src in caff]

        eps = session.execute(
            select(MigraineEpisode.started_at, MigraineEpisode.ended_at, MigraineEpisode.severity)
            .where(
                MigraineEpisode.started_at < end_utc,
                (MigraineEpisode.ended_at.is_(None)) | (MigraineEpisode.ended_at >= start_utc),
            )
        ).all()
        out["migraine"] = [
            {"start_h": off(s), "end_h": off(e) if e else None, "severity": sev}
            for s, e, sev in eps
        ]

        ck_rows = session.execute(
            select(SubjectiveCheckin).where(SubjectiveCheckin.date >= start_utc.date() - timedelta(days=1))
        ).scalars().all()
        checkin = None
        for ck in ck_rows:
            if ck.updated_at and start_utc <= ck.updated_at < end_utc:
                checkin = {
                    "h": off(ck.updated_at), "mood": ck.mood, "energy": ck.energy,
                    "stress": ck.stress, "soreness": ck.soreness,
                }
        out["checkin"] = checkin

        rhr = session.execute(
            select(MetricSample.value).where(MetricSample.metric_key == "resting_heart_rate")
            .order_by(MetricSample.ts.desc()).limit(1)
        ).scalar()
        out["_resting_hr"] = float(rhr) if rhr is not None else None

        def daily(key: str) -> float:
            v = session.execute(
                select(MetricSample.value).where(
                    MetricSample.metric_key == key,
                    MetricSample.ts >= start_utc, MetricSample.ts < end_utc,
                ).order_by(MetricSample.ts.desc()).limit(1)
            ).scalar()
            return float(v) if v is not None else 0.0

        out["_intensity"] = (daily("intensity_minutes_moderate"), daily("intensity_minutes_vigorous"))
    return out


def _gather_events(start_utc, end_utc, off) -> list[dict[str, Any]]:
    """カレンダー予定 (gcal 未設定なら空)。ウィンドウが触れる JST 日付を走査。終日除外。"""
    start_jst_d = start_utc.replace(tzinfo=UTC).astimezone(JST).date()
    end_jst_d = end_utc.replace(tzinfo=UTC).astimezone(JST).date()
    dates = {start_jst_d, end_jst_d}
    events: list[dict[str, Any]] = []
    try:
        from app.integrations.gcal import list_events_for_date

        for d in sorted(dates):
            for e in list_events_for_date(d):
                s, en = e.get("start") or "", e.get("end") or ""
                if len(s) <= 10 or len(en) <= 10:
                    continue
                sd = datetime.fromisoformat(s).astimezone(UTC).replace(tzinfo=None)
                ed = datetime.fromisoformat(en).astimezone(UTC).replace(tzinfo=None)
                if ed <= start_utc or sd >= end_utc:
                    continue
                events.append({"start_h": off(sd), "end_h": off(ed), "title": e.get("summary") or "予定"})
    except Exception:
        pass
    return events


@router.get("/api/timeline")
async def day_timeline(
    date: str | None = Query(default=None),
    window: str = Query(default="day"),
) -> dict[str, Any]:
    origin_utc, start_utc, end_utc, now_off, date_label, origin_jst = _resolve_window(window, date)
    off = _offsetter(origin_utc)
    g = _gather(start_utc, end_utc, off)
    return {
        "window": window,
        "date": date_label,
        "origin_jst": origin_jst.isoformat(),
        "span_h": SPAN_H,
        "now_h": now_off,
        "body_battery": g["body_battery"],
        "stress": g["stress"],
        "heart_rate": g["heart_rate"],
        "sleep_blocks": g["sleep_blocks"],
        "workouts": g["workouts"],
        "caffeine": g["caffeine"],
        "migraine": g["migraine"],
        "checkin": g["checkin"],
        "events": _gather_events(start_utc, end_utc, off),
    }


@router.get("/api/day-story")
async def day_story(
    date: str | None = Query(default=None),
    window: str = Query(default="day"),
) -> dict[str, Any]:
    from app.scoring.day_story import build_day_story

    origin_utc, start_utc, end_utc, now_off, date_label, origin_jst = _resolve_window(window, date)
    off = _offsetter(origin_utc)
    g = _gather(start_utc, end_utc, off)
    events = _gather_events(start_utc, end_utc, off)

    # 睡眠ブロックは複数あり得るが、build_day_story は1つ想定 → 最長を渡す
    sleep = max(g["sleep_blocks"], key=lambda b: b["end_h"] - b["start_h"], default=None)

    story = build_day_story(
        now_h=now_off,
        sleep=sleep,
        workouts=g["workouts"],
        events=events,
        steps=g["_steps"],
        heart_rate=g["_hr"],
        stress=[(p["h"], p["v"]) for p in g["stress"]],
        body_battery=[(p["h"], p["v"]) for p in g["body_battery"]],
        active_energy=g["_energy"],
        intensity_min=g["_intensity"],
        resting_hr=g["_resting_hr"],
    )
    # クイック統計 (情報量を補う数値サマリ)
    stress_vals = [p["v"] for p in g["stress"]]
    mod, vig = g["_intensity"]
    story["stats"] = {
        "steps": int(sum(v for _, v in g["_steps"])),
        "active_kcal": round(sum(v for _, v in g["_energy"])),
        "sleep_h": round(sleep["end_h"] - sleep["start_h"], 1) if sleep else None,
        "stress_avg": round(sum(stress_vals) / len(stress_vals)) if stress_vals else None,
        "caffeine_mg": round(sum(c["mg"] for c in g["caffeine"])),
        "intensity_min": int(mod + vig),
    }
    story["window"] = window
    story["date"] = date_label
    story["origin_jst"] = origin_jst.isoformat()
    story["span_h"] = SPAN_H
    story["now_h"] = now_off
    return story
