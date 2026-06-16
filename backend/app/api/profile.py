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


# ----- 個人差ファクター設定 (計算直結) -----


# UI で編集可能なフィールドと対応する UserProfile の生カラム。
# overrides[field] が None = 「自動 (config デフォルト / 派生)」、非 None = ユーザー明示。
_EDITABLE_FIELDS = (
    "age", "resting_hr", "max_hr",
    "caffeine_smoker", "caffeine_oral_contraceptives", "caffeine_pregnant",
    "caffeine_sensitivity", "caffeine_half_life_override_h",
    "wake_time", "sleep_need_min", "chronotype",
    "protein_g_per_kg", "water_ml_per_kg",
)


def _settings_dict() -> dict[str, Any]:
    """全個人差ファクター + 派生値 + 由来 + 生の上書き値を返す (設定 UI 用)。

    ``overrides[field]`` が None なら「ユーザー未設定 = 自動」。フロントは自動の
    フィールドを解決値 (派生/デフォルト) でグレー表示し、明示設定だけ × でクリアできる。
    """
    p = resolve_profile()
    with session_scope() as session:
        row = session.get(UserProfile, 1)
        overrides = {f: getattr(row, f, None) if row is not None else None for f in _EDITABLE_FIELDS}
    return {
        "overrides": overrides,
        "sex": p.sex,
        "age": p.age,
        "height_cm": p.height_cm,
        # 心拍
        "resting_hr": p.resting_hr,
        "max_hr": p.max_hr,  # 派生 (override or Tanaka 式)
        # カフェイン
        "caffeine_smoker": p.caffeine_smoker,
        "caffeine_oral_contraceptives": p.caffeine_oral_contraceptives,
        "caffeine_pregnant": p.caffeine_pregnant,
        "caffeine_sensitivity": p.caffeine_sensitivity,
        "caffeine_half_life_override_h": p.caffeine_half_life_override_h,
        "caffeine_half_life_h": round(p.caffeine_half_life_h, 2),  # 派生
        "caffeine_target_mg_per_kg": p.caffeine_target_mg_per_kg,  # 派生
        # 睡眠
        "wake_time": p.wake_time,
        "sleep_need_min": p.sleep_need_min,
        "chronotype": p.chronotype,
        # 栄養
        "protein_g_per_kg": p.protein_g_per_kg,
        "water_ml_per_kg": p.water_ml_per_kg,
        "source": p.source,
    }


@router.get("/api/settings")
async def get_settings_profile() -> dict[str, Any]:
    return _settings_dict()


class SettingsIn(BaseModel):
    """個人差ファクターの部分更新。指定したフィールドだけ上書きする。

    None を明示送信すると「config デフォルトに戻す」(NULL 化) を意味する。
    未指定 (キー無し) のフィールドは現状維持。
    """

    age: int | None = Field(default=None, ge=10, le=100)
    resting_hr: int | None = Field(default=None, ge=30, le=120)
    max_hr: int | None = Field(default=None, ge=120, le=220)
    caffeine_smoker: bool | None = None
    caffeine_oral_contraceptives: bool | None = None
    caffeine_pregnant: bool | None = None
    caffeine_sensitivity: str | None = Field(default=None, pattern="^(high|normal|low)$")
    caffeine_half_life_override_h: float | None = Field(default=None, ge=2.0, le=12.0)
    wake_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    sleep_need_min: int | None = Field(default=None, ge=240, le=660)
    chronotype: str | None = Field(default=None, pattern="^(morning|intermediate|evening)$")
    protein_g_per_kg: float | None = Field(default=None, ge=0.5, le=3.0)
    water_ml_per_kg: float | None = Field(default=None, ge=20, le=60)


# bool/None を区別したいフィールド (None 明示=NULL 化) と、それ以外
_SETTINGS_FIELDS = (
    "age", "resting_hr", "max_hr",
    "caffeine_smoker", "caffeine_oral_contraceptives", "caffeine_pregnant",
    "caffeine_sensitivity", "caffeine_half_life_override_h",
    "wake_time", "sleep_need_min", "chronotype",
    "protein_g_per_kg", "water_ml_per_kg",
)


@router.put("/api/settings")
async def put_settings_profile(body: SettingsIn) -> dict[str, Any]:
    # model_fields_set でクライアントが「実際に送ったキー」だけを反映する
    # (送られていないフィールドは触らない / 明示 None は NULL 化)
    sent = body.model_fields_set
    with session_scope() as session:
        row = session.get(UserProfile, 1)
        if row is None:
            row = UserProfile(id=1)
            session.add(row)
        for f in _SETTINGS_FIELDS:
            if f in sent:
                setattr(row, f, getattr(body, f))

    # 個人差が変わったので当日スコアを再計算
    try:
        from datetime import datetime

        from app.scoring.recompute import recompute_day
        from app.scoring.timewindow import JST

        recompute_day(datetime.now(JST).date())
    except Exception:
        pass

    return _settings_dict()


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
