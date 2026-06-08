from __future__ import annotations

import hashlib
import json
import re as _re
from datetime import UTC, datetime, timedelta
from datetime import date as date_type
from typing import Any

from sqlalchemy import func, select

from app.config import get_settings
from app.db import session_scope
from app.llm.prompts import build_messages
from app.logging import get_logger
from app.models import (
    BodyBatteryDaily,
    DailyScore,
    HrvDaily,
    LlmComment,
    SleepSession,
    WeightSample,
)

logger = get_logger(__name__)

_FALLBACK_MESSAGE = (
    "本日のデータが揃ったら、優先度の高いコンディション要因を一言で伝えます。"
    "根拠: スコアまたはサブスコアが未計算の状態です。"
)


def _gather_recent_workouts(target: date_type, days: int = 14) -> list[dict[str, Any]]:
    """直近 N 日のワークアウトを LLM に渡すために取得する。

    JST 時刻、平均/最大心拍、ペース (秒/km)、速度 (km/h) も付与する。
    LLM はこれらの履歴から「同種目の過去実績」を見て本日のペース・心拍ターゲット・
    時間・距離を **動的に** 算出する。
    """
    from zoneinfo import ZoneInfo

    from app.models import Workout

    jst = ZoneInfo("Asia/Tokyo")
    since = datetime.combine(target - timedelta(days=days), datetime.min.time())
    end = datetime.combine(target + timedelta(days=1), datetime.min.time())
    with session_scope() as session:
        rows = session.execute(
            select(Workout).where(Workout.start >= since, Workout.start < end).order_by(Workout.start)
        ).scalars().all()
        out = []
        for r in rows:
            start_jst = (
                r.start.replace(tzinfo=UTC).astimezone(jst) if r.start else None
            )
            end_jst = r.end.replace(tzinfo=UTC).astimezone(jst) if r.end else None
            duration_min = int(r.duration_s / 60) if r.duration_s else None
            distance_km = round(r.distance_m / 1000, 2) if r.distance_m else None
            pace_sec_per_km: int | None = None
            speed_kmh: float | None = None
            if r.distance_m and r.duration_s and r.distance_m > 0:
                pace_sec_per_km = int(r.duration_s / (r.distance_m / 1000))
                speed_kmh = round((r.distance_m / 1000) / (r.duration_s / 3600), 2)
            out.append(
                {
                    "date": start_jst.date().isoformat() if start_jst else None,
                    "start_jst": start_jst.strftime("%H:%M") if start_jst else None,
                    "end_jst": end_jst.strftime("%H:%M") if end_jst else None,
                    "type": r.type,
                    "duration_min": duration_min,
                    "distance_km": distance_km,
                    "pace_sec_per_km": pace_sec_per_km,
                    "speed_kmh": speed_kmh,
                    "avg_hr_bpm": int(r.avg_hr) if r.avg_hr else None,
                    "max_hr_bpm": int(r.max_hr) if r.max_hr else None,
                    "training_load": r.training_load,
                    "kcal": r.kcal,
                }
            )
        return out


_STRENGTH_TYPES = {"strength_training", "weight_training", "indoor_climbing"}


def _gather_today_activity(target: date_type) -> dict[str, Any]:
    """当日の活動・心拍・ストレスのサマリを LLM に渡せる形にする。

    - DailySummary (歩数/active_kcal/安静時心拍/VO2max/training_status)
    - HR タイムバケット (06-10/10-14/14-18/18-22 JST、avg と max)
    - Stress タイムバケット (同上、avg)
    - Stress > 50 の累積分 (高ストレス時間)
    """
    from collections import defaultdict
    from zoneinfo import ZoneInfo

    from app.models import DailySummary, MetricSample

    jst = ZoneInfo("Asia/Tokyo")
    day_start_jst = datetime.combine(target, datetime.min.time()).replace(tzinfo=jst)
    day_end_jst = day_start_jst + timedelta(days=1)
    day_start_utc = day_start_jst.astimezone(UTC).replace(tzinfo=None)
    day_end_utc = day_end_jst.astimezone(UTC).replace(tzinfo=None)

    out: dict[str, Any] = {}

    with session_scope() as session:
        ds = session.get(DailySummary, target)
        out["daily_summary"] = (
            {
                "steps": ds.steps,
                "active_kcal": ds.active_kcal,
                "resting_hr_bpm": ds.resting_hr,
                "vo2max": ds.vo2max,
                "training_status": ds.training_status,
            }
            if ds
            else None
        )

        buckets = [
            ("06-10", 6, 10),
            ("10-14", 10, 14),
            ("14-18", 14, 18),
            ("18-22", 18, 22),
        ]
        hr_rows = session.execute(
            select(MetricSample.ts, MetricSample.value, MetricSample.metric_key).where(
                MetricSample.ts >= day_start_utc,
                MetricSample.ts < day_end_utc,
                MetricSample.metric_key.in_(("heart_rate_avg", "heart_rate_max")),
            )
        ).all()
        stress_rows = session.execute(
            select(MetricSample.ts, MetricSample.value).where(
                MetricSample.ts >= day_start_utc,
                MetricSample.ts < day_end_utc,
                MetricSample.metric_key == "stress",
            )
        ).all()

    def _bucket_for(ts_utc: datetime) -> str | None:
        ts_jst = ts_utc.replace(tzinfo=UTC).astimezone(jst)
        h = ts_jst.hour
        for label, lo, hi in buckets:
            if lo <= h < hi:
                return label
        return None

    hr_avg_buckets: dict[str, list[float]] = defaultdict(list)
    hr_max_buckets: dict[str, list[float]] = defaultdict(list)
    for ts, value, key in hr_rows:
        if value is None:
            continue
        b = _bucket_for(ts)
        if b is None:
            continue
        if key == "heart_rate_avg":
            hr_avg_buckets[b].append(float(value))
        elif key == "heart_rate_max":
            hr_max_buckets[b].append(float(value))

    hr_profile: dict[str, dict[str, int | None]] = {}
    for label, _lo, _hi in buckets:
        avg_vals = hr_avg_buckets.get(label, [])
        max_vals = hr_max_buckets.get(label, [])
        if not avg_vals and not max_vals:
            hr_profile[label] = {"avg_bpm": None, "max_bpm": None, "n": 0}
        else:
            hr_profile[label] = {
                "avg_bpm": int(sum(avg_vals) / len(avg_vals)) if avg_vals else None,
                "max_bpm": int(max(max_vals)) if max_vals else None,
                "n": len(avg_vals) or len(max_vals),
            }
    out["hr_today"] = hr_profile

    stress_buckets: dict[str, list[float]] = defaultdict(list)
    high_stress_min = 0
    for ts, value in stress_rows:
        if value is None or value < 0:  # Garmin uses -1/-2 for invalid
            continue
        b = _bucket_for(ts)
        if b is None:
            continue
        stress_buckets[b].append(float(value))
        if value >= 50:  # samples spaced ~3 min, count as 3 min each
            high_stress_min += 3

    stress_profile: dict[str, dict[str, int | None]] = {}
    all_stress: list[float] = []
    for label, _lo, _hi in buckets:
        vals = stress_buckets.get(label, [])
        all_stress.extend(vals)
        stress_profile[label] = {
            "avg": int(sum(vals) / len(vals)) if vals else None,
            "max": int(max(vals)) if vals else None,
            "n": len(vals),
        }
    out["stress_today"] = {
        "buckets": stress_profile,
        "day_avg": int(sum(all_stress) / len(all_stress)) if all_stress else None,
        "day_max": int(max(all_stress)) if all_stress else None,
        "high_stress_min": high_stress_min,
    }

    return out


def _days_since_last_strength_training(target: date_type) -> int | None:
    """最後の strength_training から target までの経過日数。記録なしなら None。"""
    from app.models import Workout

    end = datetime.combine(target + timedelta(days=1), datetime.min.time())
    with session_scope() as session:
        rows = session.execute(
            select(Workout.start, Workout.type)
            .where(Workout.start < end)
            .order_by(Workout.start.desc())
            .limit(50)
        ).all()
    for start, wtype in rows:
        if wtype in _STRENGTH_TYPES or (wtype and "strength" in wtype.lower()):
            delta = (target - start.date()).days
            return delta
    return None


def _gather_recent_training_prescriptions(
    target: date_type, days: int = 21
) -> list[dict[str, Any]]:
    """過去 N 日の LLM 提示処方 (training/cardio) の exercises を抜き出す。

    LLM が前回までの処方を踏まえて漸進性で次を組めるようにする。

    同じ日に複数 LlmComment が生成されている (再生成や補正) ため、
    特定日の最新 1 件だけ採るとラッキング履歴などを取りこぼす。
    そのため日付内の全 payload を走査し、(title, weight 集合) シグネチャで
    重複排除しつつアクションを蓄積する。
    """
    from app.models import LlmComment

    since = target - timedelta(days=days)
    with session_scope() as session:
        rows = session.execute(
            select(LlmComment.date, LlmComment.generated_at, LlmComment.payload)
            .where(LlmComment.date >= since, LlmComment.date < target)
            .order_by(LlmComment.date.desc(), LlmComment.generated_at.desc())
        ).all()

    def _modality_bucket(action: dict[str, Any]) -> str:
        """アクションをモダリティに分類。category 信頼せず内容ベースで判定する。

        例: title が筋トレ系でも exercise にラッキングが入ってると category=training になりがち。
        この場合 rucking バケットとして扱い pack weight 履歴を保持したい。
        """
        title = (action.get("title") or "").lower()
        category = action.get("category") or ""
        ex_names = " ".join((e.get("name") or "") for e in (action.get("exercises") or [])).lower()
        haystack = title + " " + ex_names
        if "ラッキ" in haystack or "ruck" in haystack or "リュック" in haystack:
            return "rucking"
        if category == "cardio":
            return "cardio_other"
        if any(kw in haystack for kw in ("ジョグ", "ラン", "ウォーキ", "vr boxing", "ハイキ")):
            return "cardio_other"
        if category == "training":
            return "strength"
        return "other"

    out: list[dict[str, Any]] = []
    seen_sig: set[tuple] = set()
    # 筋トレ系 (strength) は同じレジメンが何度も出るので (date, modality) で 1 件に絞る。
    # ラッキング・有酸素系は pack weight や時間のバリエーションを保持したいので、
    # 内容ベースの dedupe (同日に同じ exercise 構成のものを除外) のみ。
    seen_date_strength: set[date_type] = set()
    for d, _ts, payload in rows:
        if not payload:
            continue
        actions = (payload or {}).get("actions") or []
        for a in actions:
            if a.get("category") not in ("training", "cardio"):
                continue
            exercises = a.get("exercises") or []
            if not exercises:
                continue
            modality = _modality_bucket(a)
            if modality == "strength" and d in seen_date_strength:
                continue
            sig = (
                d.isoformat(),
                tuple(
                    (e.get("name") or "", e.get("weight") or "", str(e.get("reps") or ""))
                    for e in exercises
                ),
            )
            if sig in seen_sig:
                continue
            seen_sig.add(sig)
            if modality == "strength":
                seen_date_strength.add(d)
            out.append(
                {
                    "date": d.isoformat(),
                    "title": a.get("title"),
                    "category": a.get("category"),
                    "modality": modality,
                    "intensity": a.get("intensity"),
                    "exercises": exercises,
                }
            )
    # 21 日 × strength 1 + cardio 多めで最大 30-40 件想定。token 抑制で 30 件。
    return out[:30]


def _gather_focus(target: date_type) -> dict[str, Any]:
    """LLM に渡す focus サマリ (現在値 + ピーク窓)。"""
    from zoneinfo import ZoneInfo

    from app.config import get_settings
    from app.models import BodyBattery, MetricSample
    from app.scoring.focus import (
        compute_focus_readiness,
        extract_peak_windows,
        predict_today_curve,
    )
    from app.scoring.recompute import _hrv_baseline

    settings = get_settings()
    tz = ZoneInfo(settings.app_tz)
    now_jst = datetime.now(tz)

    with session_scope() as session:
        sleep = session.get(SleepSession, target)
        hrv = session.get(HrvDaily, target)
        bb_latest = session.execute(
            select(BodyBattery).order_by(BodyBattery.ts.desc()).limit(1)
        ).scalar_one_or_none()

        stress_recent_avg: float | None = None
        since = now_jst.astimezone(UTC).replace(tzinfo=None) - timedelta(minutes=60)
        stress_rows = session.execute(
            select(MetricSample.value).where(
                MetricSample.metric_key == "stress",
                MetricSample.ts >= since,
                MetricSample.value.is_not(None),
                MetricSample.value >= 0,
            )
        ).all()
        if stress_rows:
            vals = [float(r[0]) for r in stress_rows]
            stress_recent_avg = sum(vals) / len(vals)

        baseline = _hrv_baseline(session, target)
        from datetime import time as _time

        try:
            h, _, m = settings.target_wake_time.partition(":")
            wake_t: _time | None = _time(int(h), int(m))
        except Exception:
            wake_t = None

        fr = compute_focus_readiness(
            now=now_jst,
            hrv_value=hrv.last_night_avg if hrv else None,
            hrv_baseline=baseline,
            body_battery_current=bb_latest.value if bb_latest else None,
            stress_recent_avg=stress_recent_avg,
            sleep_score=sleep.sleep_score if sleep else None,
            sleep_total_min=sleep.total_min if sleep else None,
            wake_time=wake_t,
        )
        curve = predict_today_curve(
            now=now_jst,
            hrv_value=hrv.last_night_avg if hrv else None,
            hrv_baseline=baseline,
            body_battery_current=bb_latest.value if bb_latest else None,
            stress_recent_avg=stress_recent_avg,
            sleep_score=sleep.sleep_score if sleep else None,
            sleep_total_min=sleep.total_min if sleep else None,
            wake_time=wake_t,
        )
        windows = extract_peak_windows(curve)

    return {
        "score": round(fr.score, 1) if fr.score is not None else None,
        "level": fr.level,
        "rationale": fr.rationale,
        "stress_recent_avg": (
            round(stress_recent_avg, 1) if stress_recent_avg is not None else None
        ),
        "peak_windows": [
            {"start": w.start_hhmm, "end": w.end_hhmm, "avg_score": w.avg_score} for w in windows
        ],
    }


def _gather_caffeine(target: date_type) -> dict[str, Any]:
    """LLM に渡すカフェイン推奨サマリ (今夜の bedtime に合わせて逆算)。"""
    from zoneinfo import ZoneInfo

    from app.api.caffeine import current_residual_mg
    from app.config import get_settings
    from app.scoring.caffeine import max_dose_for_bedtime, recommend_caffeine
    from app.scoring.sleep_plan import compute_tonight_plan

    settings = get_settings()
    tz = ZoneInfo(settings.app_tz)
    now_jst = datetime.now(tz)

    tonight = compute_tonight_plan(target)
    if not tonight.get("bedtime"):
        return {"available": False}

    with session_scope() as session:
        latest_weight = session.execute(
            select(WeightSample).order_by(WeightSample.ts.desc()).limit(1)
        ).scalar_one_or_none()
        # session 内で属性を取り出す (外に出すと DetachedInstanceError)
        weight_kg = (
            latest_weight.weight_kg if latest_weight else settings.target_weight_kg
        )
    if not weight_kg or weight_kg <= 0:
        return {"available": False}

    existing_residual = current_residual_mg(now_jst, settings.caffeine_half_life_h)

    rec = recommend_caffeine(
        now=now_jst,
        bedtime_jst_hhmm=tonight["bedtime"],
        body_weight_kg=weight_kg,
        half_life_h=settings.caffeine_half_life_h,
        vd_l_per_kg=settings.caffeine_vd_l_per_kg,
        bedtime_threshold_mg_per_l=settings.caffeine_bedtime_threshold_mg_per_l,
        min_cognitive_mg=settings.caffeine_min_cognitive_mg,
        target_dose_mg_per_kg=settings.caffeine_target_mg_per_kg,
        instant_coffee_mg_per_g=settings.instant_coffee_mg_per_g,
        cutoff_hours_before_bed=settings.caffeine_cutoff_hours_before_bed,
    )
    adjusted_max = max_dose_for_bedtime(
        hours_until_bedtime=rec.hours_until_bedtime,
        body_weight_kg=weight_kg,
        bedtime_threshold_mg_per_l=settings.caffeine_bedtime_threshold_mg_per_l,
        half_life_h=settings.caffeine_half_life_h,
        vd_l_per_kg=settings.caffeine_vd_l_per_kg,
        existing_residual_mg=existing_residual,
    )
    recommended = rec.recommended_mg
    if recommended is not None and adjusted_max < recommended:
        recommended = (
            None
            if adjusted_max < settings.caffeine_min_cognitive_mg
            else round(max(settings.caffeine_min_cognitive_mg, adjusted_max), 0)
        )
    return {
        "available": True,
        "recommended_mg": recommended,
        "instant_coffee_g": (
            round(recommended / settings.instant_coffee_mg_per_g, 1)
            if recommended
            else None
        ),
        "max_safe_mg": round(adjusted_max, 0),
        "existing_residual_mg": round(existing_residual, 1),
        "hours_until_bedtime": round(rec.hours_until_bedtime, 2),
        "bedtime_residual_mg": rec.bedtime_residual_if_consumed_mg,
        "concentration_at_bedtime_mg_per_l": rec.blood_concentration_at_bedtime_mg_per_l,
        "reason": rec.reason,
    }


def _gather_caffeine_intakes_today(target: date_type) -> list[dict[str, Any]]:
    """当日のカフェイン摂取記録 (頭痛薬含む)。LLM が二重提案を避けるため。"""
    from zoneinfo import ZoneInfo

    from app.config import get_settings
    from app.models import CaffeineIntake
    from app.scoring.timewindow import jst_day_bounds

    settings = get_settings()
    tz = ZoneInfo(settings.app_tz)
    start_utc, _ = jst_day_bounds(target)
    with session_scope() as session:
        rows = session.execute(
            select(CaffeineIntake)
            .where(CaffeineIntake.ts >= start_utc)
            .order_by(CaffeineIntake.ts)
        ).scalars().all()
        return [
            {
                "ts_jst": (
                    r.ts.replace(tzinfo=UTC).astimezone(tz).strftime("%H:%M")
                ),
                "source": r.source,
                "amount": r.amount,
                "unit": r.unit,
                "mg": r.mg,
            }
            for r in rows
        ]


def _gather_migraine_summary(target: date_type) -> dict[str, Any]:
    """偏頭痛の状態 (active かどうか + 30 日件数 + 直近 3 件)。"""
    from app.models import MigraineEpisode

    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=30)
    with session_scope() as session:
        rows = session.execute(
            select(MigraineEpisode)
            .where(MigraineEpisode.started_at >= since)
            .order_by(MigraineEpisode.started_at.desc())
        ).scalars().all()
        completed = [r for r in rows if r.ended_at is not None]
        active = next((r for r in rows if r.ended_at is None), None)
        return {
            "active": (
                {
                    "started_at": (
                        active.started_at.replace(tzinfo=UTC).isoformat()
                        if active.started_at.tzinfo is None
                        else active.started_at.isoformat()
                    ),
                    "severity": active.severity,
                }
                if active
                else None
            ),
            "count_30d": len(completed),
            "recent": [
                {
                    "duration_min": (
                        int((r.ended_at - r.started_at).total_seconds() / 60)
                        if r.ended_at
                        else None
                    ),
                    "severity": r.severity,
                }
                for r in completed[:3]
            ],
        }


def _gather_pressure() -> dict[str, Any] | None:
    """気圧スナップショット。"""
    from app.integrations.weather import get_pressure_snapshot, to_dict

    try:
        return to_dict(get_pressure_snapshot())
    except Exception as exc:  # フェールセーフ (オフライン環境等)
        logger.info("pressure_fetch_skipped", error=str(exc))
        return None


def _gather_wellbeing_alerts(
    target: date_type, pressure: dict[str, Any] | None
) -> list[dict[str, Any]]:
    from app.scoring.profile import resolve_profile
    from app.scoring.wellbeing_alerts import evaluate_alerts, to_dict

    prof = resolve_profile()
    with session_scope() as sess:
        alerts = evaluate_alerts(
            sess,
            target,
            pressure_risk_level=(pressure or {}).get("risk_level") if pressure else None,
            target_weight_kg=prof.target_weight_kg,
            weight_lower_kg=prof.target_weight_kg - 1.0,
        )
    return [to_dict(a) for a in alerts]


def _gather_today_payload(target: date_type) -> dict[str, Any]:
    from app.models import BodyBattery

    with session_scope() as session:
        score = session.get(DailyScore, target)
        sleep = session.get(SleepSession, target)
        hrv = session.get(HrvDaily, target)
        bb = session.get(BodyBatteryDaily, target)
        latest_weight = session.execute(
            select(WeightSample).order_by(WeightSample.ts.desc()).limit(1)
        ).scalar_one_or_none()
        bb_latest = session.execute(
            select(BodyBattery).order_by(BodyBattery.ts.desc()).limit(1)
        ).scalar_one_or_none()

        return {
            "score": {
                "total": score.total,
                "sleep_sub": score.sleep_sub,
                "hrv_sub": score.hrv_sub,
                "bb_sub": score.bb_sub,
                "load_sub": score.load_sub,
                "weight_sub": score.weight_sub,
                "body_fat_sub": score.body_fat_sub,
            }
            if score
            else None,
            "sleep": {
                "total_min": sleep.total_min,
                "sleep_score": sleep.sleep_score,
                "deep_min": sleep.deep_min,
                "rem_min": sleep.rem_min,
            }
            if sleep
            else None,
            "hrv": {
                "last_night_avg": hrv.last_night_avg,
                "weekly_avg": hrv.weekly_avg,
                "status": hrv.status,
            }
            if hrv
            else None,
            "body_battery": {
                "morning": bb.morning_value if bb else None,
                "current": bb_latest.value if bb_latest else None,
                "current_ts": bb_latest.ts.isoformat() if bb_latest else None,
            },
            "weight_kg": latest_weight.weight_kg if latest_weight else None,
            "body_fat_pct": latest_weight.body_fat_pct if latest_weight else None,
        }


def _gather_baselines(target: date_type, window_days: int = 28) -> dict[str, Any]:
    start = target - timedelta(days=window_days)
    with session_scope() as session:
        avg_total = session.execute(
            select(func.avg(DailyScore.total)).where(DailyScore.date >= start)
        ).scalar()
        avg_hrv = session.execute(
            select(func.avg(HrvDaily.last_night_avg)).where(HrvDaily.date >= start)
        ).scalar()
        avg_sleep_min = session.execute(
            select(func.avg(SleepSession.total_min)).where(SleepSession.date >= start)
        ).scalar()
        avg_weight = session.execute(
            select(func.avg(WeightSample.weight_kg)).where(
                WeightSample.ts >= datetime.combine(start, datetime.min.time())
            )
        ).scalar()
    return {
        "avg_total_score_28d": float(avg_total) if avg_total is not None else None,
        "avg_hrv_28d": float(avg_hrv) if avg_hrv is not None else None,
        "avg_sleep_min_28d": float(avg_sleep_min) if avg_sleep_min is not None else None,
        "avg_weight_kg_28d": float(avg_weight) if avg_weight is not None else None,
    }


def _gather_recent_trends(target: date_type, days: int = 28) -> dict[str, Any]:
    """直近の理想達成度トレンド (方向 + 達成度 + 前日比 + 前週比) を LLM 用にコンパクトに返す。

    series は重いので落とす。dashboard の /api/trends と同じ計算 (achievement + trends) を共有する。
    """
    from app.scoring import achievement as ach
    from app.scoring import trend_sources
    from app.scoring import trends as tr
    from app.scoring.profile import resolve_profile

    s = resolve_profile()
    bundle = trend_sources.collect_raw_series(target, days=days)
    hrv_bl = bundle["hrv_baseline"]

    def _ach(raw, fn):
        return [(row[0], fn(row)) for row in raw if fn(row) is not None]

    series_map = {
        "sleep": _ach(
            [r for r in bundle["sleep"] if r[1] is not None],
            lambda r: ach.sleep_achievement(total_min=r[1], garmin_sleep_score=r[2],
                                            deep_min=r[3], rem_min=r[4], light_min=r[5], awake_min=r[6]),
        ),
        "hrv": _ach(bundle["hrv"], lambda r: ach.hrv_achievement(r[1], hrv_bl)),
        "energy": _ach(bundle["energy"], lambda r: ach.energy_achievement(r[1])),
        "load": _ach(bundle["acwr"], lambda r: ach.load_achievement(r[1])),
        "weight": _ach(bundle["weight"], lambda r: ach.weight_achievement(r[1], s.target_weight_kg)),
        "body_fat": _ach(bundle["body_fat"],
                         lambda r: ach.body_fat_achievement(r[1], s.target_body_fat_pct, s.body_fat_tolerance_pct)),
    }
    out: dict[str, Any] = {}
    for key, series in series_map.items():
        t = tr.compute_trend(series, higher_is_better=True)
        out[key] = {
            "direction": t["direction"],
            "achievement": t["current"],
            "prev_day_change": t["prev_day_change"],
            "week_over_week": t["week_over_week"],
        }
    return out


def _gather_physio(target: date_type) -> dict[str, Any]:
    """生理指標 (sleep raw_json / Training Readiness 由来) を LLM に渡す。

    readiness は要因分解 (raw_json) 付き。睡眠規則性は中点の 14 日 SD。
    """
    from app.models import MetricSample
    from app.scoring.trend_sources import metric_daily_series

    out: dict[str, Any] = {}

    def _latest(key: str) -> float | None:
        pairs = metric_daily_series(key, target, 3)
        return round(pairs[-1][1], 1) if pairs else None

    out["sleep_spo2_avg_pct"] = _latest("sleep_spo2_avg")
    out["sleep_spo2_lowest_pct"] = _latest("sleep_spo2_lowest")
    out["sleep_respiration_brpm"] = _latest("sleep_respiration_avg")
    out["sleep_resting_hr_bpm"] = _latest("sleep_resting_hr")
    out["sleep_bb_recharge"] = _latest("sleep_bb_change")
    out["sleep_nap_min"] = _latest("sleep_nap_min")
    out["fitness_age"] = _latest("fitness_age")

    mid_pairs = metric_daily_series("sleep_midpoint_hour", target, 14)
    if mid_pairs:
        from app.scoring.circadian import circular_sd_hours

        values = [v for _, v in mid_pairs]
        out["sleep_midpoint_hour"] = round(values[-1], 2)
        sd = circular_sd_hours(values)
        out["sleep_midpoint_sd_14d_hour"] = round(sd, 2) if sd is not None else None

    # Training Readiness: スコア + 要因分解 (raw_json)
    with session_scope() as session:
        row = session.execute(
            select(MetricSample.value, MetricSample.raw_json)
            .where(MetricSample.metric_key == "training_readiness")
            .order_by(MetricSample.ts.desc())
            .limit(1)
        ).first()
    if row:
        out["training_readiness"] = {
            "score": float(row[0]) if row[0] is not None else None,
            **(row[1] or {}),
        }
    return out


def _gather_life_domains(target: date_type) -> dict[str, Any]:
    """ライフドメインの達成度・重み・ライフスコアを LLM 用に返す。"""
    from app.models import DomainWeight
    from app.scoring import domains as dom

    with session_scope() as session:
        rows = session.execute(select(DomainWeight)).scalars().all()
        saved = {r.domain: r.weight for r in rows}
    weights = {key: saved.get(key, 1.0) for key, _, _ in dom.LIFE_DOMAINS}
    return dom.compute_life(target, weights)


def _hash_messages(system: list[dict[str, Any]], messages: list[dict[str, Any]]) -> str:
    blob = json.dumps({"system": system, "messages": messages}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _store_comment(
    target: date_type,
    model: str,
    prompt_hash: str,
    comment: str,
    payload: dict[str, Any] | None = None,
) -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    with session_scope() as session:
        session.add(
            LlmComment(
                date=target,
                generated_at=now,
                model=model,
                prompt_hash=prompt_hash,
                comment=comment,
                payload=payload,
            )
        )


async def _call_anthropic(
    *,
    system: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    model: str,
    api_key: str,
    max_tokens: int = 6000,
) -> dict[str, Any] | None:
    """Anthropic を tool_use で呼び出して構造化 input を返す。

    submit_advice ツールの呼び出し input (``{focus, actions, rationale}``) を返す。
    呼び出しが失敗したり tool_use が無い場合は None。
    """
    from anthropic import AsyncAnthropic

    from app.llm.prompts import SUBMIT_ADVICE_TOOL

    client = AsyncAnthropic(api_key=api_key)
    resp = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
        tools=[SUBMIT_ADVICE_TOOL],
        tool_choice={"type": "tool", "name": "submit_advice"},
    )
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == "submit_advice":
            payload = block.input
            if isinstance(payload, dict):
                return _sanitize_payload(payload)
            return None
    return None


_LEAKED_TAG_RE = _re.compile(
    r"</?(focus|rationale|headline|actions|action|parameter[^>]*?|invoke[^>]*?|function_calls?)\s*/?>",
    _re.IGNORECASE,
)


def _scrub_text(s: Any) -> Any:
    if not isinstance(s, str):
        return s
    cleaned = _LEAKED_TAG_RE.sub("", s)
    cleaned = _re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned


def _sanitize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """LLM が混入させがちな XML 風タグを focus/rationale/headline/title から除去する。"""
    for k in ("headline", "focus", "rationale"):
        if k in payload:
            payload[k] = _scrub_text(payload[k])
    actions = payload.get("actions") or []
    if isinstance(actions, list):
        for a in actions:
            if not isinstance(a, dict):
                continue
            for k in ("title", "intensity", "why", "notes"):
                if k in a:
                    a[k] = _scrub_text(a[k])
    return payload


def _payload_to_prose(payload: dict[str, Any]) -> str:
    """構造化 advice を従来の人間可読プロンプト風テキストに整形 (バックアップ表示用)。"""
    lines: list[str] = []
    if focus := payload.get("focus"):
        lines.append(f"【今日のフォーカス】\n{focus}\n")
    actions = payload.get("actions") or []
    if actions:
        lines.append("【推奨アクション】")
        for a in actions:
            t = a.get("time_jst", "")
            title = a.get("title", "")
            dur = a.get("duration_min")
            intensity = a.get("intensity")
            extras = []
            if dur:
                extras.append(f"{dur}分")
            if intensity:
                extras.append(intensity)
            tail = f" ({', '.join(extras)})" if extras else ""
            lines.append(f"- [{t}] {title}{tail}")
        lines.append("")
    if rationale := payload.get("rationale"):
        lines.append(f"【根拠】\n{rationale}")
    return "\n".join(lines).strip()


async def generate_advice_for_date(target: date_type, *, force: bool = False) -> dict[str, Any]:
    settings = get_settings()
    api_key = settings.anthropic_api_key

    if not force:
        with session_scope() as session:
            today_count = session.execute(
                select(func.count(LlmComment.date)).where(LlmComment.date == target)
            ).scalar()
            if today_count and today_count >= settings.llm_max_regenerations_per_day:
                logger.info("llm_skip_rate_limit", date=str(target), count=today_count)
                return {"status": "rate_limited"}

    today_payload = _gather_today_payload(target)
    today_payload["focus"] = _gather_focus(target)
    today_payload["caffeine"] = _gather_caffeine(target)
    today_payload["caffeine_intakes_today"] = _gather_caffeine_intakes_today(target)
    today_payload["migraine"] = _gather_migraine_summary(target)
    today_payload["pressure"] = _gather_pressure()
    today_payload["alerts"] = _gather_wellbeing_alerts(target, today_payload["pressure"])
    today_payload["recent_workouts_14d"] = _gather_recent_workouts(target, days=14)
    today_payload["days_since_last_strength_training"] = _days_since_last_strength_training(target)
    today_payload["recent_training_prescriptions_21d"] = _gather_recent_training_prescriptions(target)
    today_payload.update(_gather_today_activity(target))
    today_payload["recent_trends"] = _gather_recent_trends(target)
    today_payload["life_domains"] = _gather_life_domains(target)
    today_payload["physio"] = _gather_physio(target)
    # 今夜のスリープリズム
    from app.scoring.sleep_plan import compute_tonight_plan

    today_payload["tonight_plan"] = compute_tonight_plan(target)
    # 栄養: 当日の摂取・PFC・水分・TDEE 推定 + 推奨値
    from app.scoring.nutrition import aggregate_nutrition

    with session_scope() as session:
        today_payload["nutrition"] = aggregate_nutrition(session, target)
    baselines = _gather_baselines(target)

    # Calendar 既存予定を取り込む (gcal 未設定なら空リスト)
    calendar_events: list[dict[str, Any]] = []
    try:
        from app.integrations.gcal import list_events_for_date

        calendar_events = list_events_for_date(target)
    except Exception as exc:
        logger.info("gcal_events_unavailable", error=str(exc))

    system, messages = build_messages(
        target=target,
        today_payload=today_payload,
        baselines=baselines,
        calendar_events=calendar_events,
    )
    prompt_hash = _hash_messages(system, messages)

    # ルールベース fallback advice を準備 (LLM 不通時に使う)
    def _build_rule_based_fallback() -> dict[str, Any]:
        from zoneinfo import ZoneInfo

        from app.scoring.fallback_advice import build_fallback_advice

        s = get_settings()
        now_jst = datetime.now(ZoneInfo(s.app_tz))
        return build_fallback_advice(
            now=now_jst,
            alerts=today_payload.get("alerts"),
            caffeine=today_payload.get("caffeine"),
            focus=today_payload.get("focus"),
            tonight_plan=today_payload.get("tonight_plan"),
            pressure=today_payload.get("pressure"),
            morning_light=today_payload.get("morning_light"),
        )

    if not api_key:
        fb = _build_rule_based_fallback()
        prose = _payload_to_prose(fb)
        _store_comment(target, "fallback", prompt_hash, prose, payload=fb)
        return {"status": "fallback", "comment": prose, "payload": fb, "model": "fallback"}

    try:
        payload = await _call_anthropic(
            system=system, messages=messages, model=settings.llm_model, api_key=api_key
        )
        if not payload:
            fb = _build_rule_based_fallback()
            prose = _payload_to_prose(fb)
            _store_comment(target, "fallback", prompt_hash, prose, payload=fb)
            return {
                "status": "fallback",
                "comment": prose,
                "payload": fb,
                "model": "fallback",
            }
        prose = _payload_to_prose(payload)
        _store_comment(target, settings.llm_model, prompt_hash, prose, payload=payload)
        return {
            "status": "ok",
            "comment": prose,
            "payload": payload,
            "model": settings.llm_model,
        }
    except Exception as exc:
        logger.warning("llm_call_failed", error=str(exc))
        fb = _build_rule_based_fallback()
        prose = _payload_to_prose(fb)
        _store_comment(target, "fallback", prompt_hash, prose, payload=fb)
        return {
            "status": "fallback",
            "comment": prose,
            "payload": fb,
            "model": "fallback",
            "error": str(exc),
        }


async def morning_advice_job() -> dict[str, Any]:
    target = datetime.now().date()
    return await generate_advice_for_date(target)
