from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.db import session_scope
from app.models import (
    BodyBattery,
    BodyBatteryDaily,
    DailyScore,
    DailySummary,
    HrvDaily,
    LlmComment,
    SleepSession,
    SourceSync,
    WeightSample,
    Workout,
)


def _utc_iso(dt: datetime | None) -> str | None:
    """naive な datetime は UTC 由来として扱い、明示的に +00:00 を付けて返す。

    ブラウザ側の `new Date(...)` がローカル時刻に変換してくれるようにするため。
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()

router = APIRouter()


def _today() -> date:
    return datetime.now().date()


@router.get("/api/today")
async def today() -> dict[str, Any]:
    d = _today()
    with session_scope() as session:
        score = session.get(DailyScore, d)
        sleep = session.get(SleepSession, d)
        hrv = session.get(HrvDaily, d)
        bb = session.get(BodyBatteryDaily, d)
        summary = session.get(DailySummary, d)
        weight_row = session.execute(
            select(WeightSample).order_by(WeightSample.ts.desc()).limit(1)
        ).scalar_one_or_none()
        bb_latest = session.execute(
            select(BodyBattery).order_by(BodyBattery.ts.desc()).limit(1)
        ).scalar_one_or_none()
        comment = session.execute(
            select(LlmComment)
            .where(LlmComment.date == d)
            .order_by(LlmComment.generated_at.desc())
            .limit(1)
        ).scalar_one_or_none()

        sync_rows = session.execute(select(SourceSync)).scalars().all()
        sync = {
            row.source: {
                "last_synced_at": _utc_iso(row.last_synced_at),
                "last_error": row.last_error,
            }
            for row in sync_rows
        }

        # 各サブスコアの「null である理由」を組み立てる。
        # ベースライン要件 / Garmin 未装着 / Apple Health 未連携 を区別する。
        sub_reasons = _build_sub_reasons(session, d, sleep, hrv, bb, weight_row)

        # データソース帰属
        data_sources = {
            "sleep": sleep.source if sleep else None,
            "hrv": "garmin" if hrv else None,
            "body_battery": "garmin" if bb and bb.morning_value is not None else None,
            "summary": "garmin" if summary else None,
            "weight": weight_row.source if weight_row else None,
        }

        # 各サブスコアの実世界の値とターゲット (UI 表示用)
        from app.config import get_settings
        from app.scoring.recompute import _training_load

        s = get_settings()
        acute, chronic = _training_load(session, d)
        acwr = (acute / chronic) if (acute is not None and chronic and chronic > 0) else None
        sub_context = {
            "sleep": {
                "current": sleep.total_min if sleep else None,
                # 7-9h が WHO/AASM の推奨範囲
                "target": {"min": 420, "ideal": 480, "max": 540, "unit": "分", "kind": "range"},
            },
            "hrv": {
                "current": hrv.last_night_avg if hrv else None,
                "weekly_avg": hrv.weekly_avg if hrv else None,
                # HRV は個人差大、絶対値の目標は設定せずベースライン比で判断
                "target": {"min": None, "ideal": None, "max": None, "unit": "ms", "kind": "baseline_relative"},
            },
            "body_battery": {
                "current": bb_latest.value if bb_latest else None,
                "morning": bb.morning_value if bb else None,
                # Garmin の Body Battery: 50+ 良好、80+ 高い
                "target": {"min": 50, "ideal": 80, "max": 100, "unit": "", "kind": "minimum"},
            },
            "load": {
                "acute": acute,
                "chronic": chronic,
                "acwr": acwr,
                "target": {
                    "min": 0.8,
                    "ideal": 1.0,
                    "max": 1.3,
                    "unit": "",
                    "kind": "range",
                },
            },
            "weight": {
                "current": weight_row.weight_kg if weight_row else None,
                "target": {
                    "min": round(s.target_weight_kg - 1.0, 1),
                    "ideal": s.target_weight_kg,
                    "max": round(s.target_weight_kg + 1.0, 1),
                    "unit": "kg",
                    "kind": "range",
                },
            },
            "body_fat": {
                "current": weight_row.body_fat_pct if weight_row else None,
                "target": {
                    "min": round(s.target_body_fat_pct - s.body_fat_tolerance_pct, 1),
                    "ideal": s.target_body_fat_pct,
                    "max": round(s.target_body_fat_pct + s.body_fat_tolerance_pct, 1),
                    "unit": "%",
                    "kind": "range",
                },
            },
        }

        from app.scoring.nutrition import aggregate_nutrition
        from app.scoring.sleep_plan import compute_tonight_plan

        nutrition = aggregate_nutrition(session, d)

        # 今日 (の現在時刻以降) にトレ予定があるなら、その end を拾う。
        # Healthcare 管理イベント or [hc-adjustable] のような未来予定。
        # ここでは Workout テーブルではなく、Calendar から取りに行きたいが
        # gcal は LLM 側で読んでいるので、まず Workout で完了済みのものから判定する
        # (簡易実装: 当日のワークアウトの end の最大値)
        from app.scoring.timewindow import jst_day_bounds

        _today_start, _today_end = jst_day_bounds(d)
        last_training_end = session.execute(
            select(func.max(Workout.end)).where(
                Workout.start >= _today_start,
                Workout.start < _today_end,
            )
        ).scalar()
        # naive UTC → JST aware
        from zoneinfo import ZoneInfo

        last_training_end_jst = (
            last_training_end.replace(tzinfo=UTC).astimezone(ZoneInfo("Asia/Tokyo"))
            if last_training_end
            else None
        )
        tonight_plan = compute_tonight_plan(d, last_training_end_jst=last_training_end_jst)

        # 最終更新時刻 (sync の最新 + score.computed_at + comment.generated_at の最新)
        candidates: list[datetime] = []
        for row in sync_rows:
            if row.last_synced_at:
                candidates.append(row.last_synced_at)
        if score and score.computed_at:
            candidates.append(score.computed_at)
        if comment and comment.generated_at:
            candidates.append(comment.generated_at)
        last_update = max(candidates) if candidates else None

        return {
            "date": d.isoformat(),
            "last_data_update_at": _utc_iso(last_update),
            "score": _score_to_dict(score),
            "sub_reasons": sub_reasons,
            "data_sources": data_sources,
            "sub_context": sub_context,
            "nutrition": nutrition,
            "tonight_plan": tonight_plan,
            "metrics": {
                "sleep": _sleep_to_dict(sleep),
                "hrv": _hrv_to_dict(hrv),
                "body_battery": _bb_to_dict(
                    bb,
                    current=bb_latest.value if bb_latest else None,
                    current_ts=bb_latest.ts if bb_latest else None,
                ),
                "summary": _summary_to_dict(summary),
                "weight": _weight_to_dict(weight_row),
            },
            "advice": _comment_to_dict(comment),
            "sync": sync,
        }


def _build_sub_reasons(
    session,
    target: date,
    sleep: SleepSession | None,
    hrv: HrvDaily | None,
    bb: BodyBatteryDaily | None,
    weight_row: WeightSample | None,
) -> dict[str, str | None]:
    """null サブスコアの理由文字列を返す (測定済なら None)。"""
    from app.config import get_settings
    from app.models import WeightSample as W

    settings = get_settings()
    window = settings.baseline_window_days

    # HRV: データがあれば、ベースライン (28日) 学習中かどうか
    if hrv is None or hrv.last_night_avg is None:
        hrv_reason = "Garmin 未装着 / 計測なし"
    else:
        # baseline 数を見て学習中か判定
        from datetime import timedelta as _td

        from app.models import HrvDaily as H

        bl_start = target - _td(days=window)
        n = session.execute(
            select(H.date).where(
                H.date >= bl_start,
                H.date < target,
                H.last_night_avg.is_not(None),
            )
        ).all()
        n_count = len(n)
        if n_count < window:
            hrv_reason = f"ベースライン学習中 ({n_count}/{window} 日)"
        else:
            hrv_reason = None

    # Body Battery: Garmin 専用指標
    if bb is None or bb.morning_value is None:
        bb_reason = "Garmin 未装着 / 朝の計測なし"
    else:
        bb_reason = None

    # Sleep
    if sleep is None or sleep.total_min is None:
        sleep_reason = "睡眠データなし (Garmin 未装着 / Apple Watch 未連携)"
    else:
        sleep_reason = None

    # Weight + body fat
    if weight_row is None or weight_row.weight_kg is None:
        weight_reason = "体重データなし (体組成計から Apple Health 未連携)"
        bf_reason = weight_reason
    else:
        # weight_sub には baseline 28d が必要
        from datetime import datetime as _dt
        from datetime import timedelta as _td2

        bl_start_dt = _dt.combine(target - _td2(days=window), _dt.min.time())
        n_w = session.execute(
            select(W.ts).where(W.ts >= bl_start_dt, W.weight_kg.is_not(None))
        ).all()
        if len(n_w) < window // 2:  # ゆるく半分以上で OK
            weight_reason = f"ベースライン学習中 ({len(n_w)}/{window} サンプル)"
        else:
            weight_reason = None
        # 体脂肪率は最近 7 日サンプルが要る
        if weight_row.body_fat_pct is None:
            bf_reason = "体脂肪率データなし"
        else:
            bf_reason = None

    # 訓練負荷: 直近の workout が一切なければ計測不可
    from datetime import datetime as _dt2
    from datetime import timedelta as _td3

    from app.models import Workout

    n_w_recent = session.execute(
        select(Workout.id).where(
            Workout.start
            >= _dt2.combine(target - _td3(days=14), _dt2.min.time())
        )
    ).all()
    load_reason = (
        None if len(n_w_recent) > 0 else "直近 14 日のワークアウト記録なし"
    )

    return {
        "sleep": sleep_reason,
        "hrv": hrv_reason,
        "body_battery": bb_reason,
        "load": load_reason,
        "weight": weight_reason,
        "body_fat": bf_reason,
    }


@router.get("/api/timeseries")
async def timeseries(
    metric: str = Query(...),
    days: int = Query(default=28, ge=1, le=365),
) -> dict[str, Any]:
    end = _today()
    start = end - timedelta(days=days)
    with session_scope() as session:
        if metric == "score":
            rows = session.execute(
                select(DailyScore.date, DailyScore.total)
                .where(DailyScore.date >= start)
                .order_by(DailyScore.date)
            ).all()
            data = [{"date": r[0].isoformat(), "value": r[1]} for r in rows]
        elif metric == "weight":
            rows = session.execute(
                select(WeightSample.ts, WeightSample.weight_kg)
                .where(WeightSample.ts >= datetime.combine(start, datetime.min.time()))
                .order_by(WeightSample.ts)
            ).all()
            data = [{"date": r[0].date().isoformat(), "value": r[1]} for r in rows]
        elif metric == "sleep_total_min":
            rows = session.execute(
                select(SleepSession.date, SleepSession.total_min)
                .where(SleepSession.date >= start)
                .order_by(SleepSession.date)
            ).all()
            data = [{"date": r[0].isoformat(), "value": r[1]} for r in rows]
        elif metric == "hrv":
            rows = session.execute(
                select(HrvDaily.date, HrvDaily.last_night_avg)
                .where(HrvDaily.date >= start)
                .order_by(HrvDaily.date)
            ).all()
            data = [{"date": r[0].isoformat(), "value": r[1]} for r in rows]
        else:
            data = []
        return {"metric": metric, "from": start.isoformat(), "to": end.isoformat(), "data": data}


@router.get("/api/trends")
async def trends(
    granularity: str = Query(default="daily"),
    days: int = Query(default=28, ge=7, le=365),
) -> dict[str, Any]:
    from app.scoring import trends as trend_calc

    end = _today()
    start = end - timedelta(days=days)
    with session_scope() as session:
        rows = session.execute(
            select(
                DailyScore.date,
                DailyScore.total,
                DailyScore.sleep_sub,
                DailyScore.hrv_sub,
                DailyScore.bb_sub,
                DailyScore.load_sub,
                DailyScore.weight_sub,
                DailyScore.body_fat_sub,
            )
            .where(DailyScore.date >= start)
            .order_by(DailyScore.date)
        ).all()

    by_col = trend_calc.series_by_column(rows)
    metrics = trend_calc.build_metrics(by_col, granularity=granularity)
    return {
        "granularity": granularity,
        "generated_at": _utc_iso(datetime.now(UTC).replace(tzinfo=None)),
        "metrics": metrics,
    }


def _score_to_dict(score: DailyScore | None) -> dict[str, Any] | None:
    if score is None:
        return None
    return {
        "total": score.total,
        "sleep": score.sleep_sub,
        "hrv": score.hrv_sub,
        "body_battery": score.bb_sub,
        "load": score.load_sub,
        "weight": score.weight_sub,
        "body_fat": score.body_fat_sub,
        "version": score.version,
        "computed_at": _utc_iso(score.computed_at),
    }


def _sleep_to_dict(s: SleepSession | None) -> dict[str, Any] | None:
    if s is None:
        return None
    return {
        "total_min": s.total_min,
        "deep_min": s.deep_min,
        "rem_min": s.rem_min,
        "light_min": s.light_min,
        "awake_min": s.awake_min,
        "sleep_score": s.sleep_score,
        "source": s.source,
    }


def _hrv_to_dict(h: HrvDaily | None) -> dict[str, Any] | None:
    if h is None:
        return None
    return {
        "last_night_avg": h.last_night_avg,
        "weekly_avg": h.weekly_avg,
        "status": h.status,
    }


def _bb_to_dict(
    bb: BodyBatteryDaily | None,
    *,
    current: float | None = None,
    current_ts: datetime | None = None,
) -> dict[str, Any] | None:
    if bb is None and current is None:
        return None
    return {
        "max": bb.max_value if bb else None,
        "min": bb.min_value if bb else None,
        "morning": bb.morning_value if bb else None,
        "end_of_day": bb.end_of_day if bb else None,
        "current": current,
        "current_ts": _utc_iso(current_ts),
    }


def _summary_to_dict(s: DailySummary | None) -> dict[str, Any] | None:
    if s is None:
        return None
    return {
        "steps": s.steps,
        "active_kcal": s.active_kcal,
        "resting_hr": s.resting_hr,
        "vo2max": s.vo2max,
        "training_status": s.training_status,
    }


def _weight_to_dict(w: WeightSample | None) -> dict[str, Any] | None:
    if w is None:
        return None
    return {
        "weight_kg": w.weight_kg,
        "body_fat_pct": w.body_fat_pct,
        "muscle_kg": w.muscle_kg,
        "ts": _utc_iso(w.ts),
    }


def _comment_to_dict(c: LlmComment | None) -> dict[str, Any] | None:
    if c is None:
        return None
    return {
        "comment": c.comment,
        "model": c.model,
        "generated_at": _utc_iso(c.generated_at),
        "payload": c.payload,
    }
