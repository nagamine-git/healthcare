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
from app.models.health import BodyCompositionSample
from app.scoring.body_measurement import bia_navy_discrepancy, navy_body_fat_pct, whtr, whtr_status
from app.scoring.body_trend import smoothed_body
from app.scoring.physique_gap import assess_physique_gap
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


def _latest_body_composition() -> dict[str, float | None]:
    """骨格筋率・内臓脂肪レベルの最新スクショ取込値 (手動記録、無くてもよい)。

    ⚠️ **ORM オブジェクトを session_scope の外へ返さない。** 抜けた時点で detach され、
    呼び出し側が属性に触れた瞬間 DetachedInstanceError で 500 になる
    (`/api/sleep/last-night` で同じ罠を踏んだ)。必要な値だけ素の dict にして返す。
    """
    with session_scope() as session:
        row = (
            session.execute(
                select(BodyCompositionSample)
                .order_by(BodyCompositionSample.date.desc(), BodyCompositionSample.id.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
        if row is None:
            return {"skeletal_muscle_pct": None, "visceral_fat_level": None}
        return {
            "skeletal_muscle_pct": row.skeletal_muscle_pct,
            "visceral_fat_level": row.visceral_fat_level,
        }


def _evaluate(row: BodyMeasurement | None) -> dict[str, Any]:
    """最新測定 1 件から WHtR・米海軍式体脂肪率・BIA との比較をまとめる。"""
    prof = resolve_profile()
    waist_cm = row.waist_cm if row else None
    neck_cm = row.neck_cm if row else None

    ratio = whtr(waist_cm, prof.height_cm)
    status = whtr_status(ratio)
    navy_pct = navy_body_fat_pct(waist_cm, neck_cm, prof.height_cm, prof.sex)

    bia_est = smoothed_body()  # 測定ノイズを除いた BIA 体脂肪率トレンド
    discrepancy = bia_navy_discrepancy(bia_est.body_fat_pct, navy_pct)

    # ⚠️ 生の float をそのまま返さない。BIA は元々 ±3-5pt の誤差があり、
    # 17.68893693789233% のような桁は**精度の錯覚**でしかない (実際に UI で桁溢れして
    # 隣の数値と重なる表示崩れも起きた)。表示と同じ 0.1pt 単位に丸めて返す。
    bia_pct = (
        round(bia_est.body_fat_pct, 1) if bia_est.body_fat_pct is not None else None
    )

    body_comp = _latest_body_composition()

    # 目標とのギャップ評価 (体重ギャップの正体が脂肪不足か筋量不足かを言い切る)。
    # 体重・体脂肪率(BIA)が取れていないと LBM に分解できないため縮退で available=False。
    gap = assess_physique_gap(
        weight_kg=bia_est.weight_kg,
        body_fat_pct=bia_est.body_fat_pct,
        target_weight_kg=prof.target_weight_kg,
        target_body_fat_pct=prof.target_body_fat_pct,
        body_fat_tolerance_pct=prof.body_fat_tolerance_pct,
        height_cm=prof.height_cm,
        sex=prof.sex,
        body_fat_pct_secondary=navy_pct,
        waist_cm=waist_cm,
        whtr_ratio=ratio,
        whtr_status_value=status,
        skeletal_muscle_pct=body_comp["skeletal_muscle_pct"],
        visceral_fat_level=body_comp["visceral_fat_level"],
    )

    return {
        "whtr": ratio,
        "whtr_status": status,
        "navy_body_fat_pct": navy_pct,
        "bia_body_fat_pct": bia_pct,
        "discrepancy": discrepancy,
        "height_cm": prof.height_cm,
        "sex": prof.sex,
        "gap": gap,
    }


@router.get("/api/body-measurement")
def get_body_measurement() -> dict[str, Any]:
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
def get_body_measurement_history(days: int = 90) -> dict[str, Any]:
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
def put_body_measurement(body: BodyMeasurementIn) -> dict[str, Any]:
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
