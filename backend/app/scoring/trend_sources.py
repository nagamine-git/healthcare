"""トレンド用に各指標の生値日次系列を DB から取得する。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from datetime import date as date_type
from typing import Any

from sqlalchemy import select

from app.db import session_scope
from app.models import BodyBatteryDaily, HrvDaily, SleepSession, WeightSample
from app.scoring.baselines import build_baseline
from app.scoring.recompute import _training_load


def _weight_daily(rows: list[tuple[datetime, float | None]]) -> list[tuple[date_type, float]]:
    """WeightSample (ts, value) を JST 日付ごとの中央値に集約。"""
    from app.scoring.timewindow import JST

    by_day: dict[date_type, list[float]] = {}
    for ts, v in rows:
        if v is None or ts is None:
            continue
        d = ts.replace(tzinfo=UTC).astimezone(JST).date()
        by_day.setdefault(d, []).append(float(v))
    out: list[tuple[date_type, float]] = []
    for d in sorted(by_day):
        vals = sorted(by_day[d])
        n = len(vals)
        med = vals[n // 2] if n % 2 == 1 else (vals[n // 2 - 1] + vals[n // 2]) / 2
        out.append((d, med))
    return out


def daily_acwr_series(target: date_type, days: int) -> list[tuple[date_type, float]]:
    """各日付の ACWR (acute/chronic) を計算した系列。"""
    out: list[tuple[date_type, float]] = []
    with session_scope() as session:
        for i in range(days + 1):
            d = target - timedelta(days=i)
            acute, chronic = _training_load(session, d)
            if acute is not None and chronic and chronic > 0:
                out.append((d, acute / chronic))
    out.sort(key=lambda p: p[0])
    return out


def collect_raw_series(target: date_type, days: int = 28) -> dict[str, Any]:
    """全指標の生値日次系列 + HRV ベースラインを返す。"""
    start = target - timedelta(days=days)
    with session_scope() as session:
        sleep_rows = session.execute(
            select(
                SleepSession.date, SleepSession.total_min, SleepSession.sleep_score,
                SleepSession.deep_min, SleepSession.rem_min, SleepSession.light_min,
                SleepSession.awake_min,
            ).where(SleepSession.date >= start, SleepSession.date <= target)
            .order_by(SleepSession.date)
        ).all()
        hrv_rows = session.execute(
            select(HrvDaily.date, HrvDaily.last_night_avg)
            .where(HrvDaily.date >= start, HrvDaily.date <= target)
            .order_by(HrvDaily.date)
        ).all()
        energy_rows = session.execute(
            select(BodyBatteryDaily.date, BodyBatteryDaily.morning_value)
            .where(BodyBatteryDaily.date >= start, BodyBatteryDaily.date <= target)
            .order_by(BodyBatteryDaily.date)
        ).all()
        weight_rows = session.execute(
            select(WeightSample.ts, WeightSample.weight_kg)
            .where(WeightSample.ts >= datetime.combine(start, datetime.min.time()))
            .order_by(WeightSample.ts)
        ).all()
        fat_rows = session.execute(
            select(WeightSample.ts, WeightSample.body_fat_pct)
            .where(WeightSample.ts >= datetime.combine(start, datetime.min.time()))
            .order_by(WeightSample.ts)
        ).all()
        hrv_vals = [r[1] for r in hrv_rows]

    return {
        "sleep": [tuple(r) for r in sleep_rows],
        "hrv": [(d, v) for d, v in hrv_rows if v is not None],
        "energy": [(d, v) for d, v in energy_rows if v is not None],
        "weight": _weight_daily(list(weight_rows)),
        "body_fat": _weight_daily(list(fat_rows)),
        "acwr": daily_acwr_series(target, days),
        "hrv_baseline": build_baseline(hrv_vals),
    }
