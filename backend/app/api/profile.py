"""個人プロファイル (目標体型) の取得・保存 API。

UI の理想体型シルエットで決めた目標体重・体脂肪率を user_profile に保存し、
採点・アラート・LLM・栄養が resolve_profile() 経由で参照する。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.db import session_scope
from app.models import UserProfile
from app.scoring.body_composition import assess
from app.scoring.profile import resolve_profile

router = APIRouter()


def _profile_dict() -> dict[str, Any]:
    p = resolve_profile()
    return {
        "height_cm": p.height_cm,
        "sex": p.sex,
        "target_weight_kg": p.target_weight_kg,
        "target_body_fat_pct": p.target_body_fat_pct,
        "body_fat_tolerance_pct": p.body_fat_tolerance_pct,
        "ffmi_normalized": p.ffmi_normalized,
        "source": p.source,
    }


@router.get("/api/profile")
async def get_profile() -> dict[str, Any]:
    return _profile_dict()


class ProfileIn(BaseModel):
    height_cm: float | None = Field(default=None, gt=50, lt=250)
    sex: str | None = Field(default=None, pattern="^(male|female)$")
    target_weight_kg: float = Field(gt=20, lt=200)
    target_body_fat_pct: float = Field(ge=3, le=50)
    body_fat_tolerance_pct: float | None = Field(default=None, ge=0.5, le=5)
    ffmi_normalized: float | None = Field(default=None, ge=14, le=30)


@router.put("/api/profile")
async def put_profile(body: ProfileIn) -> dict[str, Any]:
    # 有効身長 (未指定なら現在の resolve 値) で BMI を評価
    height = body.height_cm if body.height_cm is not None else resolve_profile().height_cm
    bmi = body.target_weight_kg / (height / 100.0) ** 2
    a = assess(
        weight_kg=body.target_weight_kg, bmi=bmi,
        body_fat_pct=body.target_body_fat_pct, sex=body.sex or resolve_profile().sex,
    )
    if a["level"] == "blocked":
        raise HTTPException(status_code=422, detail={"message": "; ".join(a["warnings"]), "assessment": a})

    with session_scope() as session:
        row = session.get(UserProfile, 1)
        if row is None:
            row = UserProfile(id=1)
            session.add(row)
        if body.height_cm is not None:
            row.height_cm = body.height_cm
        if body.sex is not None:
            row.sex = body.sex
        row.target_weight_kg = body.target_weight_kg
        row.target_body_fat_pct = body.target_body_fat_pct
        if body.body_fat_tolerance_pct is not None:
            row.body_fat_tolerance_pct = body.body_fat_tolerance_pct
        if body.ffmi_normalized is not None:
            row.ffmi_normalized = body.ffmi_normalized

    # 目標が変わったので当日スコアを再計算
    try:
        from datetime import datetime

        from app.scoring.recompute import recompute_day
        from app.scoring.timewindow import JST

        recompute_day(datetime.now(JST).date())
    except Exception:
        pass

    return {**_profile_dict(), "assessment": a}
