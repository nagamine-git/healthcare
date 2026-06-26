"""健康診断のアップロード(テキスト/画像)・取得 API。判断材料として保存する。"""

from __future__ import annotations

from datetime import date as date_type
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import get_settings
from app.db import session_scope
from app.llm.checkup import extract_checkup
from app.models.health import HealthCheckup
from app.scoring.checkup import abnormal_summary, evaluate
from app.scoring.timewindow import app_today

router = APIRouter()


class CheckupIn(BaseModel):
    text: str | None = None
    image_base64: str | None = None
    media_type: str = "image/png"
    date: str | None = None


def _latest_payload(session) -> dict[str, Any]:
    row = session.query(HealthCheckup).order_by(HealthCheckup.date.desc(), HealthCheckup.id.desc()).first()
    history = [
        {"id": r.id, "date": r.date.isoformat()}
        for r in session.query(HealthCheckup).order_by(HealthCheckup.date.desc()).limit(20).all()
    ]
    latest = None
    if row is not None:
        latest = {
            "id": row.id, "date": row.date.isoformat(), "values": row.values or [],
            "summary": abnormal_summary(row.values or []),
        }
    return {"latest": latest, "history": history}


@router.get("/api/checkup")
async def get_checkup() -> dict[str, Any]:
    with session_scope() as session:
        return _latest_payload(session)


@router.post("/api/checkup")
async def post_checkup(body: CheckupIn) -> dict[str, Any]:
    if not body.text and not body.image_base64:
        raise HTTPException(status_code=400, detail="text か image_base64 が必要です")
    extracted = await extract_checkup(
        text=body.text, image_b64=body.image_base64, media_type=body.media_type
    )
    if extracted is None:
        raise HTTPException(status_code=502, detail="抽出に失敗しました(LLM 未設定または読取不可)")

    items = get_settings().checkup_items
    source = "image" if body.image_base64 else "text"
    exams = extracted.get("exams") or []
    stored = 0
    with session_scope() as session:
        for exam in exams:
            values = evaluate(exam.get("values", []), items)
            if not values:
                continue
            # 実施日: exam > body.date > 今日
            if exam.get("date"):
                d = date_type.fromisoformat(exam["date"])
            elif body.date:
                d = date_type.fromisoformat(body.date)
            else:
                d = app_today()
            # 同一実施日は upsert(再アップロードで重複させない)
            row = session.query(HealthCheckup).filter(HealthCheckup.date == d).first()
            if row is None:
                row = HealthCheckup(date=d)
                session.add(row)
            row.values = values
            row.source = source
            row.raw_text = (body.text or "")[:4000]
            stored += 1
        if stored == 0:
            raise HTTPException(status_code=422, detail="有効な項目を検出できませんでした")
        session.flush()
        payload = _latest_payload(session)
    payload["stored"] = stored
    return payload


@router.delete("/api/checkup/{checkup_id}")
async def delete_checkup(checkup_id: int) -> dict[str, Any]:
    with session_scope() as session:
        row = session.get(HealthCheckup, checkup_id)
        if row is None:
            raise HTTPException(status_code=404, detail="not found")
        session.delete(row)
        session.flush()
        return _latest_payload(session)


def latest_checkup_summary() -> str | None:
    """最新健診の異常値サマリ(LLM コーチング文脈用)。無ければ None。"""
    with session_scope() as session:
        row = (
            session.query(HealthCheckup)
            .order_by(HealthCheckup.date.desc(), HealthCheckup.id.desc())
            .first()
        )
        if row is None:
            return None
        return abnormal_summary(row.values or [])
