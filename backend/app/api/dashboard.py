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
    MetricSample,
    SleepSession,
    SourceSync,
    WeightSample,
    Workout,
)
from app.scoring.timewindow import app_today, jst_day_bounds


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
    return app_today()


@router.get("/api/today")
async def today(
    lat: float | None = Query(default=None, description="気圧取得用の緯度 (省略時 config)"),
    lon: float | None = Query(default=None, description="気圧取得用の経度"),
) -> dict[str, Any]:
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
        # 当日分に限定 (前日夜の高い値を「現在値」と誤表示しない)
        _bb_start, _bb_end = jst_day_bounds(d)
        bb_latest = session.execute(
            select(BodyBattery)
            .where(BodyBattery.ts >= _bb_start, BodyBattery.ts < _bb_end)
            .order_by(BodyBattery.ts.desc())
            .limit(1)
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

        # 欠損した一次指標の統計的補完 (ウォッチ未装着日など)。実測が欠けている時だけ算出。
        imputed: dict[str, Any] = {}
        if not (sleep and sleep.sleep_score is not None) or hrv is None or bb is None or summary is None:
            from app.scoring.imputation import impute_day
            imputed = impute_day(d, only_missing=True)

        # 各サブスコアの実世界の値とターゲット (UI 表示用)
        from app.scoring.profile import resolve_profile
        from app.scoring.recompute import _training_load

        s = resolve_profile()
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

        # --- 大気質 + 朝光暴露 (Focus に環境補正を入れる) ---
        from app.integrations.weather import (
            air_quality_to_dict,
            get_air_quality_snapshot,
        )
        from app.scoring.morning_light import compute_morning_light_score

        air_snap = get_air_quality_snapshot(latitude=lat, longitude=lon)
        air_quality = air_quality_to_dict(air_snap)
        morning_light = compute_morning_light_score(session, d)

        # --- 集中力 (Focus Readiness) ---
        # 現在時刻における認知準備度を proxy 指標から算出する。
        # 直接的な集中力測定 (EEG 等) ではないことに注意。
        focus = _build_focus(
            session,
            target=d,
            sleep=sleep,
            hrv=hrv,
            bb_current=bb_latest.value if bb_latest else None,
            pm2_5=air_snap.pm2_5 if air_snap else None,
            morning_light_score=morning_light.get("score"),
        )

        # --- 気圧 (片頭痛トリガー) ---
        pressure = _build_pressure(lat=lat, lon=lon)

        # --- Wellbeing Alerts (ヤバい状態の自動検知) ---
        from app.scoring.profile import resolve_profile
        from app.scoring.wellbeing_alerts import evaluate_alerts
        from app.scoring.wellbeing_alerts import to_dict as alert_to_dict

        _prof = resolve_profile()
        _bmi_floor = round(18.5 * (_prof.height_cm / 100) ** 2, 1)
        alerts_raw = evaluate_alerts(
            session,
            d,
            pressure_risk_level=(pressure or {}).get("risk_level") if pressure else None,
            target_weight_kg=_prof.target_weight_kg,
            weight_lower_kg=_bmi_floor,
        )
        alerts = [alert_to_dict(a) for a in alerts_raw]

        # --- カフェイン提案 ---
        # 1コンパートメント薬物動態モデルで「今飲んでも就寝に影響しない最大量」を逆算。
        caffeine = _build_caffeine(
            tonight_plan=tonight_plan,
            current_weight_kg=weight_row.weight_kg if weight_row else None,
        )

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
            "imputed": imputed,
            "sub_context": sub_context,
            "nutrition": nutrition,
            "tonight_plan": tonight_plan,
            "focus": focus,
            "caffeine": caffeine,
            "pressure": pressure,
            "air_quality": air_quality,
            "morning_light": morning_light,
            "alerts": alerts,
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


def _build_focus(
    session,
    *,
    target: date,
    sleep: SleepSession | None,
    hrv: HrvDaily | None,
    bb_current: float | None,
    pm2_5: float | None = None,
    morning_light_score: float | None = None,
) -> dict[str, Any]:
    """現在時刻における集中可能性 (proxy) を返す。"""
    from zoneinfo import ZoneInfo

    from app.config import get_settings
    from app.scoring.focus import (
        compute_focus_readiness,
        extract_peak_windows,
        predict_today_curve,
    )
    from app.scoring.recompute import _hrv_baseline

    settings = get_settings()
    tz = ZoneInfo(settings.app_tz)
    now_jst = datetime.now(tz)

    # 直近 60 分のストレス平均 (Garmin は -1/-2 を invalid に使う)
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
    wake_t = None
    try:
        h, _, m = settings.target_wake_time.partition(":")
        from datetime import time as _time

        wake_t = _time(int(h), int(m))
    except Exception:
        wake_t = None

    fr = compute_focus_readiness(
        now=now_jst,
        hrv_value=hrv.last_night_avg if hrv else None,
        hrv_baseline=baseline,
        body_battery_current=bb_current,
        stress_recent_avg=stress_recent_avg,
        sleep_score=sleep.sleep_score if sleep else None,
        sleep_total_min=sleep.total_min if sleep else None,
        wake_time=wake_t,
        pm2_5=pm2_5,
        morning_light_score=morning_light_score,
    )
    curve = predict_today_curve(
        now=now_jst,
        hrv_value=hrv.last_night_avg if hrv else None,
        hrv_baseline=baseline,
        body_battery_current=bb_current,
        stress_recent_avg=stress_recent_avg,
        sleep_score=sleep.sleep_score if sleep else None,
        sleep_total_min=sleep.total_min if sleep else None,
        wake_time=wake_t,
        pm2_5=pm2_5,
        morning_light_score=morning_light_score,
    )
    windows = extract_peak_windows(curve)

    return {
        "score": round(fr.score, 1) if fr.score is not None else None,
        "level": fr.level,
        "rationale": fr.rationale,
        "components": {
            "hrv": round(fr.components.hrv, 1) if fr.components.hrv is not None else None,
            "body_battery": (
                round(fr.components.body_battery, 1)
                if fr.components.body_battery is not None
                else None
            ),
            "stress": round(fr.components.stress, 1) if fr.components.stress is not None else None,
            "sleep": round(fr.components.sleep, 1) if fr.components.sleep is not None else None,
            "circadian": (
                round(fr.components.circadian, 1)
                if fr.components.circadian is not None
                else None
            ),
            "air_quality": (
                round(fr.components.air_quality, 1)
                if fr.components.air_quality is not None
                else None
            ),
            "morning_light": (
                round(fr.components.morning_light, 1)
                if fr.components.morning_light is not None
                else None
            ),
        },
        "curve": curve,
        "peak_windows": [
            {
                "start": w.start_hhmm,
                "end": w.end_hhmm,
                "avg_score": w.avg_score,
            }
            for w in windows
        ],
        "stress_recent_avg": (
            round(stress_recent_avg, 1) if stress_recent_avg is not None else None
        ),
        "disclaimer": "wearable データによる proxy 指標で、直接的な認知測定 (EEG 等) ではありません。",
    }


def _build_pressure(
    *, lat: float | None = None, lon: float | None = None
) -> dict[str, Any] | None:
    """気圧スナップショット (Open-Meteo) を返す。失敗時 None。

    取得した過去系列を surface_pressure_hpa に永続化し、頭痛トリガー分析の
    気圧履歴を当日まで前進させる (アーカイブ API の数日遅延を埋める)。
    """
    from app.integrations.weather import get_pressure_snapshot, to_dict

    result = to_dict(get_pressure_snapshot(latitude=lat, longitude=lon))
    if result and result.get("series"):
        try:
            from app.ingest.pressure_history import store_pressure_points

            store_pressure_points(result["series"])
        except Exception:
            pass
    return result


def _build_caffeine(
    *,
    tonight_plan: dict[str, Any] | None,
    current_weight_kg: float | None,
) -> dict[str, Any]:
    """カフェイン推奨摂取量を返す。

    bedtime が無い (= tonight_plan が出ない異常系) や体重 0 のときは空レスポンス。
    """
    from zoneinfo import ZoneInfo

    from app.api.caffeine import current_residual_mg
    from app.config import get_settings
    from app.scoring.caffeine import (
        predict_decay_curve,
        recommend_caffeine,
    )

    settings = get_settings()
    if tonight_plan is None or not tonight_plan.get("bedtime"):
        return {"available": False, "reason": "tonight_plan が未計算"}

    from app.scoring.profile import resolve_profile
    weight_kg = current_weight_kg if current_weight_kg else resolve_profile().target_weight_kg
    if not weight_kg or weight_kg <= 0:
        return {"available": False, "reason": "体重データなし"}

    tz = ZoneInfo(settings.app_tz)
    now_jst = datetime.now(tz)

    # 本日の摂取記録からの現時点残量
    existing_residual = current_residual_mg(
        now_jst, settings.caffeine_half_life_h,
        absorption_half_life_h=settings.caffeine_absorption_half_life_h,
    )

    rec = recommend_caffeine(
        now=now_jst,
        bedtime_jst_hhmm=tonight_plan["bedtime"],
        body_weight_kg=weight_kg,
        half_life_h=settings.caffeine_half_life_h,
        vd_l_per_kg=settings.caffeine_vd_l_per_kg,
        bedtime_threshold_mg_per_l=settings.caffeine_bedtime_threshold_mg_per_l,
        min_cognitive_mg=settings.caffeine_min_cognitive_mg,
        target_dose_mg_per_kg=settings.caffeine_target_mg_per_kg,
        instant_coffee_mg_per_g=settings.instant_coffee_mg_per_g,
        cutoff_hours_before_bed=settings.caffeine_cutoff_hours_before_bed,
        absorption_half_life_h=settings.caffeine_absorption_half_life_h,
    )
    # max_safe を existing_residual で減算 (recommend_caffeine 経由で渡せないので
    # 上書きする形)
    from app.scoring.caffeine import max_dose_for_bedtime

    adjusted_max_safe = max_dose_for_bedtime(
        hours_until_bedtime=rec.hours_until_bedtime,
        body_weight_kg=weight_kg,
        bedtime_threshold_mg_per_l=settings.caffeine_bedtime_threshold_mg_per_l,
        half_life_h=settings.caffeine_half_life_h,
        vd_l_per_kg=settings.caffeine_vd_l_per_kg,
        existing_residual_mg=existing_residual,
        absorption_half_life_h=settings.caffeine_absorption_half_life_h,
    )
    # 既存残量を考慮した再計算が必要なケース (adjusted_max_safe < 現推奨 mg)
    recommended_mg = rec.recommended_mg
    if rec.recommended_mg is not None and adjusted_max_safe < rec.recommended_mg:
        # 既に体内に十分残ってる → 推奨量を下げるか、認知最低量を下回るなら None
        if adjusted_max_safe < settings.caffeine_min_cognitive_mg:
            recommended_mg = None
        else:
            recommended_mg = round(max(settings.caffeine_min_cognitive_mg, adjusted_max_safe), 1)

    # 就寝時刻 datetime (今夜)
    bh, _, bm = tonight_plan["bedtime"].partition(":")
    bedtime_dt = now_jst.replace(hour=int(bh), minute=int(bm), second=0, microsecond=0)
    if bedtime_dt <= now_jst:
        bedtime_dt = bedtime_dt + timedelta(days=1)

    # 推奨量を「今」飲んだ場合の血中濃度カーブ (UI のグラフ用)
    decay_curve: list[dict[str, float | str]] = []
    if recommended_mg:
        decay_curve = predict_decay_curve(
            dose_mg=float(recommended_mg),
            intake_time=now_jst,
            bedtime=bedtime_dt,
            body_weight_kg=weight_kg,
            half_life_h=settings.caffeine_half_life_h,
            vd_l_per_kg=settings.caffeine_vd_l_per_kg,
            absorption_half_life_h=settings.caffeine_absorption_half_life_h,
        )

    # 既存残量が反映された coffee_g とサマリ
    instant_coffee_g = (
        round(recommended_mg / settings.instant_coffee_mg_per_g, 2)
        if recommended_mg
        else None
    )
    final_reason = rec.reason
    if existing_residual > 0 and recommended_mg != rec.recommended_mg:
        final_reason = (
            f"既に体内に {existing_residual:.1f}mg 残存。"
            + (
                f"安全上限を更新 → {adjusted_max_safe:.1f}mg"
                if recommended_mg
                else "追加摂取は非推奨"
            )
        )

    return {
        "available": True,
        "recommended_mg": recommended_mg,
        "instant_coffee_g": instant_coffee_g,
        "max_safe_mg": round(adjusted_max_safe, 1),
        "min_cognitive_mg": rec.min_cognitive_mg,
        "hours_until_bedtime": round(rec.hours_until_bedtime, 2),
        "bedtime": tonight_plan["bedtime"],
        "body_weight_kg": round(weight_kg, 1),
        "half_life_h": rec.half_life_h,
        "bedtime_residual_if_consumed_mg": rec.bedtime_residual_if_consumed_mg,
        "blood_concentration_at_bedtime_mg_per_l": (
            rec.blood_concentration_at_bedtime_mg_per_l
        ),
        "existing_residual_mg": round(existing_residual, 1),
        "reason": final_reason,
        "decay_curve": decay_curve,
        "disclaimer": (
            "1コンパートメント・1次吸収/消失 (Bateman) モデルによる推定。算術的には 0.1mg "
            "精度ですが、律速は消失半減期で、個人差 (CYP1A2 遺伝多型・喫煙↓・経口避妊薬↑) "
            "により 2-12h と幅があり、これが mg 換算の不確実性を支配します。"
        ),
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
    from app.scoring import achievement as ach
    from app.scoring import trend_sources
    from app.scoring import trends as tr
    from app.scoring.profile import resolve_profile

    s = resolve_profile()
    bundle = trend_sources.collect_raw_series(_today(), days=days)
    weekly = granularity == "weekly"

    def _ach_series(raw, fn):
        out = []
        for row in raw:
            a = fn(row)
            if a is not None:
                out.append((row[0], a))
        return out

    def _raw_pairs(raw):
        return [(row[0], row[1]) for row in raw]

    def _series_out(pairs):
        return tr.weekly_average(pairs) if weekly else tr.daily_series(pairs)

    def _metric(label, unit, ideal, raw_pairs, ach_series, subtitle=None):
        trend = tr.compute_trend(ach_series, higher_is_better=True)
        out_series = _series_out(raw_pairs)
        reg_input = [(date.fromisoformat(p["date"]), p["value"]) for p in out_series]
        return {
            "label": label,
            "unit": unit,
            "ideal": ideal,
            "raw_series": out_series,
            "current_raw": round(raw_pairs[-1][1], 2) if raw_pairs else None,
            "achievement": trend["current"],
            "achievement_prev_day_change": trend["prev_day_change"],
            "achievement_week_over_week": trend["week_over_week"],
            "direction": trend["direction"],
            "regression": tr.linear_regression_endpoints(reg_input),
            "subtitle": subtitle,
        }

    sleep_raw = [r for r in bundle["sleep"] if r[1] is not None]
    sleep_pairs = [(r[0], r[1]) for r in sleep_raw]
    sleep_ach = _ach_series(
        sleep_raw,
        lambda r: ach.sleep_achievement(
            total_min=r[1], garmin_sleep_score=r[2],
            deep_min=r[3], rem_min=r[4], light_min=r[5], awake_min=r[6],
        ),
    )
    hrv_bl = bundle["hrv_baseline"]
    metrics = {
        "sleep": _metric("睡眠", "分", {"type": "band", "lo": ach.SLEEP_BAND_LO, "hi": ach.SLEEP_BAND_HI},
                         sleep_pairs, sleep_ach),
        "hrv": _metric(
            "自律神経 (HRV)", "ms",
            {"type": "upper", "good_line": round(hrv_bl.mean, 1) if hrv_bl else None},
            _raw_pairs(bundle["hrv"]),
            _ach_series(bundle["hrv"], lambda r: ach.hrv_achievement(r[1], hrv_bl)),
        ),
        "energy": _metric(
            "エネルギー", "",
            {"type": "upper", "good_line": ach.ENERGY_GOOD},
            _raw_pairs(bundle["energy"]),
            _ach_series(bundle["energy"], lambda r: ach.energy_achievement(r[1])),
        ),
        "load": _metric(
            "運動負荷 (ACWR)", "",
            {"type": "band", "lo": ach.LOAD_BAND_LO, "hi": ach.LOAD_BAND_HI},
            _raw_pairs(bundle["acwr"]),
            _ach_series(bundle["acwr"], lambda r: ach.load_achievement(r[1])),
        ),
        "weight": _metric(
            "体重", "kg",
            {"type": "band", "lo": round(s.target_weight_kg - 1.0, 1), "hi": round(s.target_weight_kg + 1.0, 1)},
            _raw_pairs(bundle["weight"]),
            _ach_series(bundle["weight"], lambda r: ach.weight_achievement(r[1], s.target_weight_kg)),
        ),
        "body_fat": _metric(
            "体脂肪率", "%",
            {"type": "band",
             "lo": round(s.target_body_fat_pct - s.body_fat_tolerance_pct, 1),
             "hi": round(s.target_body_fat_pct + s.body_fat_tolerance_pct, 1)},
            _raw_pairs(bundle["body_fat"]),
            _ach_series(bundle["body_fat"],
                        lambda r: ach.body_fat_achievement(r[1], s.target_body_fat_pct, s.body_fat_tolerance_pct)),
        ),
    }

    # --- 生理指標 (sleep raw_json / Training Readiness 由来の MetricSample) ---
    today = _today()

    def _physio(key: str):
        return trend_sources.metric_daily_series(key, today, days)

    def _ach_map(pairs, fn):
        out = []
        for d, v in pairs:
            a = fn(v)
            if a is not None:
                out.append((d, a))
        return out

    readiness_pairs = _physio("training_readiness")
    if readiness_pairs:
        metrics["readiness"] = _metric(
            "攻め時 (Readiness)", "",
            {"type": "upper", "good_line": 70},
            readiness_pairs, list(readiness_pairs),
        )

    spo2_pairs = _physio("sleep_spo2_avg")
    if spo2_pairs:
        spo2_low = _physio("sleep_spo2_lowest")
        metrics["spo2"] = _metric(
            "血中酸素 (睡眠)", "%",
            {"type": "band", "lo": 94, "hi": 100},
            spo2_pairs, _ach_map(spo2_pairs, ach.spo2_achievement),
            subtitle=f"最低 {spo2_low[-1][1]:.0f}% (直近)" if spo2_low else None,
        )

    resp_pairs = _physio("sleep_respiration_avg")
    if resp_pairs:
        metrics["respiration"] = _metric(
            "呼吸数 (睡眠)", "brpm",
            {"type": "band", "lo": ach.RESPIRATION_BAND_LO, "hi": ach.RESPIRATION_BAND_HI},
            resp_pairs, _ach_map(resp_pairs, ach.respiration_achievement),
        )

    rhr_pairs = _physio("sleep_resting_hr")
    if rhr_pairs:
        metrics["rhr_night"] = _metric(
            "夜間心拍", "bpm",
            {"type": "band", "lo": ach.RHR_NIGHT_BAND_LO, "hi": ach.RHR_NIGHT_BAND_HI},
            rhr_pairs, _ach_map(rhr_pairs, ach.rhr_night_achievement),
        )

    mid_pairs = _physio("sleep_midpoint_hour")
    if mid_pairs:
        from app.scoring.circadian import circular_mean_hour, circular_sd_hours

        mid_values = [v for _, v in mid_pairs]
        center = circular_mean_hour(mid_values) or 3.0
        recent = [v for d, v in mid_pairs if d > today - timedelta(days=14)]
        sd14 = circular_sd_hours(recent)
        metrics["sleep_midpoint"] = _metric(
            "睡眠中点 (リズム)", "時",
            {"type": "band", "lo": round(center - 0.75, 2), "hi": round(center + 0.75, 2)},
            mid_pairs,
            _ach_map(mid_pairs, lambda v: ach.band_achievement(v, center - 0.75, center + 0.75, 0.75)),
            subtitle=f"ばらつき ±{sd14:.1f}h (14日)" if sd14 is not None else None,
        )

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
    from app.api.advice_feedback import feedback_map

    return {
        "comment": c.comment,
        "model": c.model,
        "generated_at": _utc_iso(c.generated_at),
        "payload": c.payload,
        "feedback": feedback_map(c.date),
    }
