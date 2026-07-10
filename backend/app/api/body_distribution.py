"""体型の母集団分布 API。

最新の体組成 (WeightSample) + プロフィール (年齢/性別/身長/目標) から、
BMI / 体脂肪率 / FFMI の値・母集団 mean/sd・percentile・目標値をまとめて返す。
基準値・percentile ロジックは scoring/population_norms に集約 (ここは取得して渡すだけ)。
"""

from __future__ import annotations

from datetime import UTC, datetime
from datetime import date as date_type
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter
from sqlalchemy import select

from app.config import get_settings
from app.db import session_scope
from app.models import DailySummary, MetricSample, WeightSample
from app.scoring.population_norms import build_distribution
from app.scoring.profile import resolve_profile

router = APIRouter()


def _local_date(ts: datetime | None) -> date_type | None:
    """UTC naive の ts を app_tz の暦日に変換 (参照レコードの鮮度表示用)。"""
    if ts is None:
        return None
    tz = ZoneInfo(get_settings().app_tz)
    return ts.replace(tzinfo=UTC).astimezone(tz).date()


@router.get("/api/physique/distribution")
async def get_physique_distribution() -> dict[str, Any]:
    prof = resolve_profile()
    with session_scope() as session:
        row = (
            session.execute(select(WeightSample).order_by(WeightSample.ts.desc()).limit(1))
            .scalars()
            .first()
        )
        weight_kg = row.weight_kg if row else None
        body_fat_pct = row.body_fat_pct if row else None
        # 体組成 (BMI/体脂肪/FFMI) の参照日時 = 最新 WeightSample の app_tz 日付
        body_comp_as_of = _local_date(row.ts) if row else None
        # 心肺: 最新の非null VO2max (Garmin 実測)。日付も参照日時として保持。
        measured = (
            session.execute(
                select(DailySummary.vo2max, DailySummary.date)
                .where(DailySummary.vo2max.is_not(None))
                .order_by(DailySummary.date.desc())
                .limit(1)
            )
            .first()
        )
        vo2max: float | None = measured[0] if measured else None
        vo2max_as_of: date_type | None = measured[1] if measured else None
        # Garmin 実測が無ければ、公表式による推定 (metric_sample: vo2max_estimated) で代替
        vo2max_estimated = False
        if vo2max is None:
            est = (
                session.execute(
                    select(MetricSample.value, MetricSample.ts)
                    .where(MetricSample.metric_key == "vo2max_estimated",
                           MetricSample.value.is_not(None))
                    .order_by(MetricSample.ts.desc())
                    .limit(1)
                )
                .first()
            )
            if est is not None:
                vo2max = float(est[0])
                vo2max_as_of = _local_date(est[1])
                vo2max_estimated = True
    result = build_distribution(
        weight_kg=weight_kg,
        body_fat_pct=body_fat_pct,
        age=prof.age,
        sex=prof.sex,
        height_cm=prof.height_cm,
        target_weight_kg=prof.target_weight_kg,
        target_body_fat_pct=prof.target_body_fat_pct,
        body_fat_tolerance_pct=prof.body_fat_tolerance_pct,
        vo2max=vo2max,
        vo2max_estimated=vo2max_estimated,
    )
    result["body_comp_as_of"] = body_comp_as_of.isoformat() if body_comp_as_of else None
    result["vo2max_as_of"] = vo2max_as_of.isoformat() if vo2max_as_of else None
    return result
