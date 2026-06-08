"""栄養データ (Apple Health 経由) の集計。

専用テーブルを持たず ``metric_sample`` から on-the-fly で集計する。
当日の記録が薄い場合は直近 14 日の平均で推定値も併せて返す。
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import timedelta
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import MetricSample
from app.scoring.timewindow import jst_day_bounds, jst_window_start

# Apple Health の食事系メトリクスキー (Health Auto Export が送る実際の名前)
_NUTRITION_KEYS = {
    "kcal_intake": "dietary_energy",
    "protein_g": "protein",
    "fat_g": "total_fat",
    "carb_g": "carbohydrates",
    "water_ml": "dietary_water",
    "fiber_g": "fiber",
    "sugar_g": "sugar",
    "sodium_mg": "sodium",
}

# active+basal energy = 当日の TDEE 推定
_ENERGY_KEYS = ("active_energy", "basal_energy_burned")


def _sum_for_day(session: Session, metric_key: str, target: date_type) -> float | None:
    """JST 暦の target 日の合計 (DB は UTC naive なので JST→UTC 境界で範囲指定)。"""
    start, end = jst_day_bounds(target)
    val = session.execute(
        select(func.sum(MetricSample.value)).where(
            and_(
                MetricSample.metric_key == metric_key,
                MetricSample.ts >= start,
                MetricSample.ts < end,
            )
        )
    ).scalar()
    return float(val) if val is not None else None


def _avg_daily(
    session: Session,
    metric_key: str,
    target: date_type,
    window_days: int,
    *,
    min_value: float = 1.0,
) -> tuple[float | None, int]:
    """直近 N 日 (JST 暦、当日は除く) の日次合計の平均 + 集計対象日数を返す。"""
    start = jst_window_start(window_days, target)
    end, _ = jst_day_bounds(target)  # 当日 JST 00:00 (UTC) を上限
    # DB は UTC naive。JST 暦の「日」でグルーピングするには ts に +9h オフセットを掛けて
    # 日付を取り出す。SQLite の datetime() で表現。
    jst_date_expr = func.date(MetricSample.ts, "+9 hours").label("d")
    rows = session.execute(
        select(
            jst_date_expr,
            func.sum(MetricSample.value).label("s"),
        )
        .where(
            and_(
                MetricSample.metric_key == metric_key,
                MetricSample.ts >= start,
                MetricSample.ts < end,
            )
        )
        .group_by(jst_date_expr)
    ).all()
    daily = [r[1] for r in rows if r[1] is not None and r[1] >= min_value]
    if not daily:
        return None, 0
    return float(sum(daily) / len(daily)), len(daily)


def _bmr_mifflin(weight_kg: float, height_cm: float, age: int, sex: str) -> float:
    """Mifflin-St Jeor 式の基礎代謝量 (kcal/日)。"""
    sex_offset = 5 if sex.lower().startswith("m") else -161
    return 10.0 * weight_kg + 6.25 * height_cm - 5.0 * age + sex_offset


def _garmin_active_kcal_for_day(session: Session, target: date_type) -> float | None:
    """Garmin の DailySummary から当日の活動消費 (kcal) を取得。"""
    from app.models import DailySummary

    row = session.get(DailySummary, target)
    return row.active_kcal if row and row.active_kcal is not None else None


def _garmin_active_kcal_avg(session: Session, target: date_type, window_days: int) -> float | None:
    from app.models import DailySummary

    start = target - timedelta(days=window_days)
    rows = session.execute(
        select(DailySummary.active_kcal).where(
            and_(DailySummary.date >= start, DailySummary.date < target)
        )
    ).all()
    vals = [r[0] for r in rows if r[0] is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def _hae_active_kcal_for_day(session: Session, target: date_type) -> float | None:
    """HAE の active_energy を 1 日合計で取得 (Garmin が無い場合のフォールバック)。"""
    return _sum_for_day(session, "active_energy", target)


def _hae_active_kcal_avg(session: Session, target: date_type, window_days: int) -> float | None:
    avg, _ = _avg_daily(session, "active_energy", target, window_days, min_value=50.0)
    return avg


def aggregate_nutrition(session: Session, target: date_type) -> dict[str, Any]:
    """当日の栄養合計 + 推定 + ステータスを返す。

    TDEE = Mifflin-St Jeor BMR + 当日の active_kcal (Garmin DailySummary 優先)。
    HAE の active_energy / basal_energy は cumulative で重複加算されるリスクが高いため
    使わない。
    """
    from app.scoring.profile import resolve_profile
    settings = get_settings()
    prof = resolve_profile()
    out: dict[str, Any] = {}

    # BMR (定数)
    # 現体重を使うのが厳密だが、目標体重との差が小さいので target_weight_kg で代用
    bmr = _bmr_mifflin(
        prof.target_weight_kg,
        prof.height_cm,
        settings.user_age,
        prof.sex,
    )

    # 当日の活動消費: Garmin daily_summary 優先、無ければ HAE active_energy
    active_today = _garmin_active_kcal_for_day(session, target)
    active_avg = _garmin_active_kcal_avg(session, target, 14)
    if active_today is None:
        active_today = _hae_active_kcal_for_day(session, target)
    if active_avg is None:
        active_avg = _hae_active_kcal_avg(session, target, 14)

    tdee_today = bmr + active_today if active_today is not None else None
    tdee_avg = bmr + active_avg if active_avg is not None else None
    out["tdee"] = {
        "value": tdee_today if tdee_today is not None else tdee_avg,
        "estimated": tdee_today is None and tdee_avg is not None,
        "today_actual": tdee_today,
        "avg_14d": tdee_avg,
        "bmr": round(bmr, 0),
        "active_kcal_today": active_today,
        "active_kcal_avg_14d": round(active_avg, 0) if active_avg else None,
    }

    # 水分は Garmin Hydration を優先
    garmin_water = _sum_for_day(session, "garmin_hydration_ml", target)
    garmin_water_avg, _gw_n = _avg_daily(session, "garmin_hydration_ml", target, 14, min_value=100.0)

    # 食事系の min_value (それ未満はログ無し扱い)
    nutrition_min = {
        "kcal_intake": 200.0,
        "protein_g": 5.0,
        "fat_g": 5.0,
        "carb_g": 10.0,
        "water_ml": 100.0,
        "fiber_g": 1.0,
        "sugar_g": 1.0,
        "sodium_mg": 50.0,
    }
    # 推定窓: 食事は毎日記録するとは限らないので 60 日まで広げる
    estimation_window = {
        "kcal_intake": 60,
        "protein_g": 60,
        "fat_g": 60,
        "carb_g": 60,
        "water_ml": 30,
        "fiber_g": 60,
        "sugar_g": 60,
        "sodium_mg": 60,
    }

    for our_key, metric in _NUTRITION_KEYS.items():
        min_v = nutrition_min.get(our_key, 1.0)
        win = estimation_window.get(our_key, 14)
        if our_key == "water_ml" and (garmin_water or garmin_water_avg):
            today_val = garmin_water
            avg_val = garmin_water_avg
            n_days = _gw_n
        else:
            today_val = _sum_for_day(session, metric, target)
            avg_val, n_days = _avg_daily(session, metric, target, win, min_value=min_v)
        # 当日値が閾値未満なら「未記録」扱い
        today_logged = today_val is not None and today_val >= min_v
        if not today_logged and avg_val is None:
            out[our_key] = {
                "value": None,
                "estimated": False,
                "today_actual": today_val,
                "avg_14d": None,
                "estimation_n_days": 0,
            }
        elif not today_logged:
            out[our_key] = {
                "value": avg_val,
                "estimated": True,
                "today_actual": today_val,
                "avg_14d": avg_val,
                "estimation_n_days": n_days,
            }
        else:
            out[our_key] = {
                "value": today_val,
                "estimated": False,
                "today_actual": today_val,
                "avg_14d": avg_val,
                "estimation_n_days": n_days,
            }

    # 目標値 (体重ベース)。min/ideal/max の範囲で持つ。
    weight_kg = prof.target_weight_kg
    tdee_value = out["tdee"]["value"]

    out["targets"] = {
        "kcal_intake": (
            {
                "min": round(tdee_value * 0.9) if tdee_value else None,
                "ideal": round(tdee_value) if tdee_value else None,
                "max": round(tdee_value * 1.1) if tdee_value else None,
                "unit": "kcal",
                "kind": "range",  # TDEE±10% 内が良い
            }
            if tdee_value
            else None
        ),
        "protein_g": {
            "min": round(weight_kg * 1.6, 1),
            "ideal": round(weight_kg * settings.target_protein_g_per_kg, 1),
            "max": round(weight_kg * 2.5, 1),
            "unit": "g",
            "kind": "minimum",  # 多くて困らない (上限緩い)
        },
        "fat_g": {
            # 脂質: 全体カロリーの 25-30%、9 kcal/g
            "min": round(tdee_value * 0.25 / 9, 1) if tdee_value else 40.0,
            "ideal": round(tdee_value * 0.275 / 9, 1) if tdee_value else 50.0,
            "max": round(tdee_value * 0.35 / 9, 1) if tdee_value else 60.0,
            "unit": "g",
            "kind": "range",
        },
        "carb_g": {
            # 炭水化物: 残り (100% - protein% - fat%)、4 kcal/g
            # protein 113g = ~30%、fat 25-30% を引いた 40-45% を炭水化物に
            "min": round(tdee_value * 0.40 / 4, 1) if tdee_value else 150.0,
            "ideal": round(tdee_value * 0.45 / 4, 1) if tdee_value else 180.0,
            "max": round(tdee_value * 0.55 / 4, 1) if tdee_value else 210.0,
            "unit": "g",
            "kind": "range",
        },
        "water_ml": {
            "min": round(weight_kg * 30),
            "ideal": round(weight_kg * settings.target_water_ml_per_kg),
            "max": None,
            "unit": "mL",
            "kind": "minimum",
        },
        "fiber_g": {
            # 成人男性の目安 (厚労省): 21g 以上、25-30g が望ましい
            "min": 21.0,
            "ideal": 27.0,
            "max": None,
            "unit": "g",
            "kind": "minimum",
        },
        "sugar_g": {
            # WHO 推奨: 添加糖 1日 25g 未満。total sugar として 50g 未満を緩い max に
            "min": None,
            "ideal": 25.0,
            "max": 50.0,
            "unit": "g",
            "kind": "range",
        },
        "sodium_mg": {
            # 日本人男性目標 (DG): 7.5g/日 = 7500mg 未満。WHO 2000mg 推奨
            "min": None,
            "ideal": 2000.0,
            "max": 7500.0,
            "unit": "mg",
            "kind": "range",
        },
    }

    # 記録充実度: 1 つでも今日の dietary_* が入っていれば logged=true
    logged_today = any(
        (out[k]["today_actual"] or 0) > 0
        for k in ("kcal_intake", "protein_g", "fat_g", "carb_g")
    )
    out["logged_today"] = logged_today

    return out
