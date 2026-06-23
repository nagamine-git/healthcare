"""体型の母集団分布 API。

最新の体組成 (WeightSample) + プロフィール (年齢/性別/身長/目標) から、
BMI / 体脂肪率 / FFMI の値・母集団 mean/sd・percentile・目標値をまとめて返す。
基準値・percentile ロジックは scoring/population_norms に集約 (ここは取得して渡すだけ)。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from app.db import session_scope
from app.models import DailySummary, WeightSample
from app.scoring.population_norms import build_distribution
from app.scoring.profile import resolve_profile

router = APIRouter()


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
        # 心肺: 最新の非null VO2max (Garmin 実測)。
        vo2max = (
            session.execute(
                select(DailySummary.vo2max)
                .where(DailySummary.vo2max.is_not(None))
                .order_by(DailySummary.date.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
    return build_distribution(
        weight_kg=weight_kg,
        body_fat_pct=body_fat_pct,
        age=prof.age,
        sex=prof.sex,
        height_cm=prof.height_cm,
        target_weight_kg=prof.target_weight_kg,
        target_body_fat_pct=prof.target_body_fat_pct,
        body_fat_tolerance_pct=prof.body_fat_tolerance_pct,
        vo2max=vo2max,
    )
