"""周径測定 (ウエスト/首/胸/ヒップ) の取得・保存 API。

体重・体脂肪率(BIA)だけでは測定誤差が大きいため、メジャーで直接測る周径を
2本目の評価軸として保持する。ロジック (WHtR・米海軍式体脂肪率・BIA との乖離) は
scoring/body_measurement.py に集約し、ここは薄く保つ。
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.db import session_scope
from app.models import BodyMeasurement
from app.scoring.body_measurement import bia_navy_discrepancy, navy_body_fat_pct, whtr, whtr_status
from app.scoring.body_trend import smoothed_body
from app.scoring.profile import resolve_profile
from app.scoring.timewindow import app_today

router = APIRouter()

_HISTORY_LIMIT = 180


def _row_dict(r: BodyMeasurement) -> dict[str, Any]:
    return {
        "date": r.date.isoformat(),
        "waist_cm": r.waist_cm,
        "neck_cm": r.neck_cm,
        "chest_cm": r.chest_cm,
        "hip_cm": r.hip_cm,
        "note": r.note,
    }


def _evaluate(row: BodyMeasurement | None) -> dict[str, Any]:
    """最新測定 1 件から WHtR・米海軍式体脂肪率・BIA との比較をまとめる。"""
    prof = resolve_profile()
    waist_cm = row.waist_cm if row else None
    neck_cm = row.neck_cm if row else None

    ratio = whtr(waist_cm, prof.height_cm)
    navy_pct = navy_body_fat_pct(waist_cm, neck_cm, prof.height_cm, prof.sex)

    bia_est = smoothed_body()  # 測定ノイズを除いた BIA 体脂肪率トレンド
    discrepancy = bia_navy_discrepancy(bia_est.body_fat_pct, navy_pct)

    return {
        "whtr": ratio,
        "whtr_status": whtr_status(ratio),
        "navy_body_fat_pct": navy_pct,
        "bia_body_fat_pct": bia_est.body_fat_pct,
        "discrepancy": discrepancy,
        "height_cm": prof.height_cm,
        "sex": prof.sex,
    }


@router.get("/api/body-measurement")
async def get_body_measurement() -> dict[str, Any]:
    with session_scope() as session:
        row = (
            session.execute(select(BodyMeasurement).order_by(BodyMeasurement.date.desc()).limit(1))
            .scalars()
            .first()
        )
        latest = _row_dict(row) if row else None
        evaluation = _evaluate(row)
    return {"latest": latest, **evaluation}


@router.get("/api/body-measurement/history")
async def get_body_measurement_history(days: int = 90) -> dict[str, Any]:
    days = max(1, min(days, _HISTORY_LIMIT))
    today = app_today()
    start = today.fromordinal(today.toordinal() - days + 1)
    with session_scope() as session:
        rows = (
            session.execute(
                select(BodyMeasurement)
                .where(BodyMeasurement.date >= start)
                .order_by(BodyMeasurement.date.asc())
            )
            .scalars()
            .all()
        )
        return {"history": [_row_dict(r) for r in rows]}


class BodyMeasurementIn(BaseModel):
    date: str | None = None
    waist_cm: float | None = None
    neck_cm: float | None = None
    chest_cm: float | None = None
    hip_cm: float | None = None
    note: str | None = None


@router.put("/api/body-measurement")
async def put_body_measurement(body: BodyMeasurementIn) -> dict[str, Any]:
    """確認済みの値を日付ごとに upsert。周径が全て None (note のみ) は 422。"""
    if all(v is None for v in (body.waist_cm, body.neck_cm, body.chest_cm, body.hip_cm)):
        raise HTTPException(status_code=422, detail="保存する測定値がありません")
    d = date_type.fromisoformat(body.date) if body.date else app_today()
    with session_scope() as session:
        row = session.get(BodyMeasurement, d)
        if row is None:
            row = BodyMeasurement(date=d)
            session.add(row)
        row.waist_cm = body.waist_cm
        row.neck_cm = body.neck_cm
        row.chest_cm = body.chest_cm
        row.hip_cm = body.hip_cm
        row.note = body.note
        session.flush()
        latest = _row_dict(row)
        evaluation = _evaluate(row)
    return {"latest": latest, **evaluation}
