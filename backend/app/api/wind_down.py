"""就寝前の状態から「すぐ寝ろ」か「呼吸法を何分か」を出し分ける API。

判定ロジック本体は ``scoring/wind_down.py`` (DB 非依存の純関数)。ここでは既存の
就寝逆算 (``scoring/sleep_plan.py``)・HRV/安静時心拍のベースライン
(``scoring/baselines.py``)・カフェイン体内残量 (``api/caffeine.py``) を集めて渡すだけ。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import session_scope
from app.models import DailySummary, HrvDaily, SleepSession
from app.scoring.baselines import build_baseline
from app.scoring.sleep_plan import compute_tonight_plan
from app.scoring.timewindow import app_today
from app.scoring.wind_down import recommend_wind_down

router = APIRouter()


def _last_and_baseline(
    session: Session, model: Any, value_col: Any, date_col: Any, target, window_days: int
) -> tuple[float | None, float | None]:
    """(直近値, ベースライン平均) を返す共通ヘルパー。

    HRV (HrvDaily.last_night_avg) にも安静時心拍 (DailySummary.resting_hr) にも
    同じ「直近 N 日、当日は除いてベースライン」パターンが使えるため共通化する。
    """
    start = target - timedelta(days=window_days)
    rows = session.execute(
        select(date_col, value_col)
        .where(date_col >= start, date_col <= target)
        .order_by(date_col)
    ).all()
    if not rows:
        return None, None
    baseline_vals = [v for d, v in rows if d < target and v is not None]
    baseline = build_baseline(baseline_vals)
    last = next((v for _d, v in reversed(rows) if v is not None), None)
    return last, (baseline.mean if baseline is not None else None)


def _estimate_sleep_debt_min(session: Session, target, *, window_days: int, sleep_need_min: int) -> float | None:
    """直近 window_days 夜の (目標睡眠−実睡眠) 不足分の合計 (黒字の夜は 0 扱い)。

    急性の睡眠負債は直近数日の不足を見るのが実用的 (長期窓では平均化されて鈍る)。
    専用の睡眠負債モジュールが無いための簡易推定であり、正式な負債モデルではない。
    """
    start = target - timedelta(days=window_days)
    rows = session.execute(
        select(SleepSession.total_min).where(
            SleepSession.date >= start, SleepSession.date < target
        )
    ).all()
    values = [r[0] for r in rows if r[0] is not None]
    if not values:
        return None
    return sum(max(0.0, sleep_need_min - v) for v in values)


@router.get("/api/wind-down")
async def get_wind_down() -> dict[str, Any]:
    from app.api.caffeine import current_residual_mg
    from app.scoring.profile import resolve_profile

    settings = get_settings()
    tz = ZoneInfo(settings.app_tz)
    now = datetime.now(tz)
    target = app_today()
    prof = resolve_profile()

    plan = compute_tonight_plan(target, now=now)
    target_bedtime = datetime.fromisoformat(plan["bedtime_iso"])

    caffeine_mg = current_residual_mg(
        now, prof.caffeine_half_life_h,
        absorption_half_life_h=settings.caffeine_absorption_half_life_h,
    )

    with session_scope() as session:
        hrv_last, hrv_baseline = _last_and_baseline(
            session, HrvDaily, HrvDaily.last_night_avg, HrvDaily.date,
            target, settings.baseline_window_days,
        )
        rhr_last, rhr_baseline = _last_and_baseline(
            session, DailySummary, DailySummary.resting_hr, DailySummary.date,
            target, settings.baseline_window_days,
        )
        sleep_debt_min = _estimate_sleep_debt_min(
            session, target,
            window_days=settings.sleep_debt_window_days,
            sleep_need_min=prof.sleep_need_min,
        )

    result = recommend_wind_down(
        now=now,
        target_bedtime=target_bedtime,
        sleep_debt_min=sleep_debt_min,
        hrv_last=hrv_last,
        hrv_baseline=hrv_baseline,
        resting_hr=rhr_last,
        resting_hr_baseline=rhr_baseline,
        caffeine_mg_on_board=caffeine_mg,
        wind_down_window_min=settings.wind_down_window_min,
        large_sleep_debt_min=settings.wind_down_large_sleep_debt_min,
        bedtime_soon_min=settings.wind_down_bedtime_soon_min,
        hrv_drop_strong_pct=settings.wind_down_hrv_drop_strong_pct,
        hrv_drop_mild_pct=settings.wind_down_hrv_drop_mild_pct,
        rhr_rise_strong_bpm=settings.wind_down_rhr_rise_strong_bpm,
        rhr_rise_mild_bpm=settings.wind_down_rhr_rise_mild_bpm,
        caffeine_residual_mg_threshold=settings.wind_down_caffeine_residual_mg,
        cyclic_sigh_min_min=settings.wind_down_cyclic_sigh_min_min,
        cyclic_sigh_max_min=settings.wind_down_cyclic_sigh_max_min,
        slow6_min_min=settings.wind_down_slow6_min_min,
        slow6_max_min=settings.wind_down_slow6_max_min,
    )
    result["target_bedtime"] = plan["bedtime"]
    result["inputs"] = {
        "sleep_debt_min": sleep_debt_min,
        "hrv_last": hrv_last,
        "hrv_baseline": round(hrv_baseline, 1) if hrv_baseline is not None else None,
        "resting_hr": rhr_last,
        "resting_hr_baseline": round(rhr_baseline, 1) if rhr_baseline is not None else None,
        "caffeine_mg_on_board": round(caffeine_mg, 1) if caffeine_mg is not None else None,
    }
    return result
