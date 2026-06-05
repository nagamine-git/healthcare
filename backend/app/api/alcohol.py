"""アルコール摂取の手動記録 API。

純アルコール量 (g) = 量(ml) × ABV(%) / 100 × 0.8 (g/ml)
1 drink ≈ 10g (Pietilä 2018)、20g 超で深い睡眠・HRV に明確な影響。

プリセット:
- ビール (中ジョッキ 350ml × 5%) ≈ 14g
- 缶ビール 500ml × 5% ≈ 20g
- ワイングラス (150ml × 13%) ≈ 16g
- 日本酒 1 合 (180ml × 15%) ≈ 22g
- 焼酎水割り (60ml × 25%) ≈ 12g
- ハイボール (60ml × 40%) ≈ 19g
- ストロング系チューハイ 350ml × 9% ≈ 25g
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import get_settings
from app.db import session_scope
from app.models import AlcoholIntake

router = APIRouter()


Source = Literal[
    "beer_glass",
    "beer_can_500",
    "wine_glass",
    "sake_go",
    "shochu_mizuwari",
    "highball",
    "strong_chuhai",
    "manual",
]


# (default_amount, default_ml, default_abv, default_grams)
# default_grams は固定値 (純アルコール g)。manual は g 直接入力。
PRESET_DEFAULTS: dict[str, dict[str, Any]] = {
    "beer_glass": {
        "unit": "杯", "default_amount": 1.0, "default_ml": 350, "default_abv": 5.0,
        "grams_per_unit": 14.0,
    },
    "beer_can_500": {
        "unit": "缶", "default_amount": 1.0, "default_ml": 500, "default_abv": 5.0,
        "grams_per_unit": 20.0,
    },
    "wine_glass": {
        "unit": "杯", "default_amount": 1.0, "default_ml": 150, "default_abv": 13.0,
        "grams_per_unit": 16.0,
    },
    "sake_go": {
        "unit": "合", "default_amount": 1.0, "default_ml": 180, "default_abv": 15.0,
        "grams_per_unit": 22.0,
    },
    "shochu_mizuwari": {
        "unit": "杯", "default_amount": 1.0, "default_ml": 60, "default_abv": 25.0,
        "grams_per_unit": 12.0,
    },
    "highball": {
        "unit": "杯", "default_amount": 1.0, "default_ml": 60, "default_abv": 40.0,
        "grams_per_unit": 19.0,
    },
    "strong_chuhai": {
        "unit": "缶", "default_amount": 1.0, "default_ml": 350, "default_abv": 9.0,
        "grams_per_unit": 25.0,
    },
    "manual": {
        "unit": "g", "default_amount": 0.0, "default_ml": 0, "default_abv": 0.0,
        "grams_per_unit": 1.0,
    },
}


class AlcoholIntakeIn(BaseModel):
    source: Source
    amount: float = Field(gt=0)
    note: str | None = None
    ts_iso: str | None = None
    # 任意でカスタム ml / ABV を指定 (より正確な記録用)
    override_ml: float | None = Field(default=None, gt=0)
    override_abv_pct: float | None = Field(default=None, gt=0, le=100)


class AlcoholIntakeOut(BaseModel):
    id: int
    ts: str
    ts_jst: str
    source: str
    amount: float
    unit: str
    amount_ml: float | None
    abv_pct: float | None
    grams: float
    note: str | None


@router.post("/api/alcohol", response_model=AlcoholIntakeOut)
async def add_alcohol_intake(body: AlcoholIntakeIn) -> AlcoholIntakeOut:
    settings = get_settings()
    if body.source not in PRESET_DEFAULTS:
        raise HTTPException(status_code=400, detail=f"unknown source: {body.source}")

    preset = PRESET_DEFAULTS[body.source]

    if body.override_ml is not None and body.override_abv_pct is not None:
        # 純アルコール g = ml × ABV/100 × 0.8 (g/ml)
        grams_per_unit = body.override_ml * body.override_abv_pct / 100 * 0.8
        amount_ml = body.override_ml
        abv = body.override_abv_pct
    else:
        grams_per_unit = float(preset["grams_per_unit"])
        amount_ml = (
            float(preset["default_ml"]) if preset["default_ml"] else None
        )
        abv = float(preset["default_abv"]) if preset["default_abv"] else None

    grams = body.amount * grams_per_unit

    if body.ts_iso:
        try:
            ts = datetime.fromisoformat(body.ts_iso)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"invalid ts_iso: {exc}") from exc
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        ts_utc = ts.astimezone(UTC).replace(tzinfo=None)
    else:
        ts_utc = datetime.now(UTC).replace(tzinfo=None)

    with session_scope() as session:
        row = AlcoholIntake(
            ts=ts_utc,
            source=body.source,
            amount_ml=amount_ml,
            abv_pct=abv,
            grams=grams,
            note=body.note,
        )
        session.add(row)
        session.flush()
        return _to_out(row, settings.app_tz, body.amount, preset["unit"])


@router.get("/api/alcohol")
async def list_alcohol_intakes(hours: int = 168) -> dict[str, Any]:
    """直近 hours 時間の摂取記録 (デフォルト 7d)。"""
    settings = get_settings()
    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=hours)
    with session_scope() as session:
        rows = session.execute(
            select(AlcoholIntake).where(AlcoholIntake.ts >= since).order_by(AlcoholIntake.ts)
        ).scalars().all()
        items: list[dict[str, Any]] = []
        for r in rows:
            preset = PRESET_DEFAULTS.get(r.source, {"unit": "?"})
            # amount は記録時点の grams / grams_per_unit から逆算 (近似)
            grams_per_unit = float(preset.get("grams_per_unit", 1.0))
            amount = r.grams / grams_per_unit if grams_per_unit > 0 else r.grams
            items.append(_to_out(r, settings.app_tz, amount, preset["unit"]).model_dump())
        return {
            "items": items,
            "total_grams": sum(r.grams for r in rows),
            "drinks_equivalent": round(sum(r.grams for r in rows) / 10.0, 1),
        }


@router.delete("/api/alcohol/{intake_id}")
async def delete_alcohol_intake(intake_id: int) -> dict[str, Any]:
    with session_scope() as session:
        row = session.get(AlcoholIntake, intake_id)
        if row is None:
            raise HTTPException(status_code=404, detail="not found")
        session.delete(row)
        return {"deleted": intake_id}


@router.get("/api/alcohol/presets")
async def alcohol_presets() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, info in PRESET_DEFAULTS.items():
        out[k] = {
            "unit": info["unit"],
            "default_amount": info["default_amount"],
            "default_ml": info["default_ml"],
            "default_abv": info["default_abv"],
            "grams_per_unit": info["grams_per_unit"],
            "default_grams": float(info["default_amount"])
            * float(info["grams_per_unit"]),
        }
    return out


def last_night_alcohol_grams(now_jst: datetime) -> float:
    """前夜 (前日 18:00 〜 当日 06:00 JST) のアルコール摂取量合計。

    深い睡眠と HRV への影響を当日の Focus に反映するため。
    """
    settings = get_settings()
    tz = ZoneInfo(settings.app_tz)
    today_6 = now_jst.replace(hour=6, minute=0, second=0, microsecond=0)
    if now_jst.hour < 6:
        # 早朝 06 前なら、参照ウィンドウは前々日 18:00 〜 前日 06:00 ではなく
        # 「直近の夜間」: 前日 18:00 〜 当日の今
        start_jst = today_6 - timedelta(hours=12)
        end_jst = now_jst
    else:
        start_jst = today_6 - timedelta(hours=12)  # 前日 18:00
        end_jst = today_6
    start_utc = start_jst.astimezone(UTC).replace(tzinfo=None)
    end_utc = end_jst.astimezone(UTC).replace(tzinfo=None)
    _ = tz  # tz は読み出し時の参考、変換は astimezone で完了
    with session_scope() as session:
        rows = session.execute(
            select(AlcoholIntake.grams).where(
                AlcoholIntake.ts >= start_utc, AlcoholIntake.ts < end_utc
            )
        ).all()
    return sum(float(r[0]) for r in rows if r[0] is not None)


def _to_out(
    row: AlcoholIntake, tz_name: str, amount: float, unit: str
) -> AlcoholIntakeOut:
    tz = ZoneInfo(tz_name)
    ts_utc = row.ts.replace(tzinfo=UTC) if row.ts.tzinfo is None else row.ts
    ts_jst = ts_utc.astimezone(tz)
    now_jst = datetime.now(tz)
    same_day = ts_jst.date() == now_jst.date()
    ts_label = (
        ts_jst.strftime("%H:%M") if same_day else ts_jst.strftime("%m/%d %H:%M")
    )
    return AlcoholIntakeOut(
        id=row.id,
        ts=ts_utc.isoformat(),
        ts_jst=ts_label,
        source=row.source,
        amount=amount,
        unit=unit,
        amount_ml=row.amount_ml,
        abv_pct=row.abv_pct,
        grams=row.grams,
        note=row.note,
    )
