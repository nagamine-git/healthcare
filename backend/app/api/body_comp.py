"""体組成(BIA)スクショの取り込み・取得 API。

体重/体脂肪率は Apple Health 経由で別途取得済み。ここは標準で取れない
骨格筋量・内臓脂肪レベル・基礎代謝のみを手動スクショから保持する。
OCR は誤りうる前提で extract(抽出のみ)→ put(確認後に保存)の 2 段。
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db import session_scope
from app.llm.body_comp import extract_body_comp
from app.models.health import BodyCompositionSample
from app.scoring.timewindow import app_today

router = APIRouter()

_HISTORY_LIMIT = 60


def _row_dict(r: BodyCompositionSample) -> dict[str, Any]:
    return {
        "id": r.id,
        "date": r.date.isoformat(),
        "skeletal_muscle_kg": r.skeletal_muscle_kg,
        "skeletal_muscle_pct": r.skeletal_muscle_pct,
        "visceral_fat_level": r.visceral_fat_level,
        "bmr_kcal": r.bmr_kcal,
    }


def _payload(session) -> dict[str, Any]:
    rows = (
        session.query(BodyCompositionSample)
        .order_by(BodyCompositionSample.date.desc(), BodyCompositionSample.id.desc())
        .limit(_HISTORY_LIMIT)
        .all()
    )
    history = [_row_dict(r) for r in rows]
    return {"latest": history[0] if history else None, "history": history}


@router.get("/api/body-composition")
async def get_body_composition() -> dict[str, Any]:
    with session_scope() as session:
        return _payload(session)


class ExtractIn(BaseModel):
    image_base64: str
    media_type: str = "image/png"


@router.post("/api/body-composition/extract")
async def extract(body: ExtractIn) -> dict[str, Any]:
    """スクショから数値を抽出して下書きを返す(保存はしない。確認・修正用)。"""
    draft = await extract_body_comp(image_b64=body.image_base64, media_type=body.media_type)
    if draft is None:
        raise HTTPException(status_code=502, detail="抽出に失敗(LLM 未設定または読取不可)")
    return {"draft": draft}


class BodyCompIn(BaseModel):
    date: str | None = None
    skeletal_muscle_kg: float | None = None
    skeletal_muscle_pct: float | None = None
    visceral_fat_level: float | None = None
    bmr_kcal: float | None = None


@router.put("/api/body-composition")
async def put_body_composition(body: BodyCompIn) -> dict[str, Any]:
    """確認済みの値を日付ごとに upsert。全項目 None なら 422。"""
    if all(
        v is None
        for v in (
            body.skeletal_muscle_kg,
            body.skeletal_muscle_pct,
            body.visceral_fat_level,
            body.bmr_kcal,
        )
    ):
        raise HTTPException(status_code=422, detail="保存する値がありません")
    d = date_type.fromisoformat(body.date) if body.date else app_today()
    with session_scope() as session:
        row = session.query(BodyCompositionSample).filter(BodyCompositionSample.date == d).first()
        if row is None:
            row = BodyCompositionSample(date=d)
            session.add(row)
        row.skeletal_muscle_kg = body.skeletal_muscle_kg
        row.skeletal_muscle_pct = body.skeletal_muscle_pct
        row.visceral_fat_level = body.visceral_fat_level
        row.bmr_kcal = body.bmr_kcal
        session.flush()
        return _payload(session)


@router.delete("/api/body-composition/{sample_id}")
async def delete_body_composition(sample_id: int) -> dict[str, Any]:
    with session_scope() as session:
        row = session.get(BodyCompositionSample, sample_id)
        if row is None:
            raise HTTPException(status_code=404, detail="not found")
        session.delete(row)
        session.flush()
        return _payload(session)
