"""スマホ依存トラッキング API — スクショ取込 (複数可) と集計取得。"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.db import session_scope
from app.models import ScreenTimeSample
from app.scoring.screentime import summarize

router = APIRouter()


class STImage(BaseModel):
    image_base64: str
    media_type: str = "image/png"


class STImportIn(BaseModel):
    images: list[STImage] | None = None
    image_base64: str | None = None  # 後方互換 (単一)
    media_type: str = "image/png"


def _apply(session, got: dict[str, Any]) -> None:
    try:
        pstart = date_type.fromisoformat(str(got["period_start"])[:10])
    except (ValueError, KeyError):
        return
    ptype = got.get("period_type")
    if ptype not in ("day", "week"):
        return
    row = session.execute(
        select(ScreenTimeSample).where(
            ScreenTimeSample.period_type == ptype, ScreenTimeSample.period_start == pstart
        )
    ).scalars().first()
    if row is None:
        row = ScreenTimeSample(period_type=ptype, period_start=pstart, daily_min=0)
        session.add(row)
    row.daily_min = float(got["daily_min"])
    row.total_min = float(got["total_min"]) if got.get("total_min") else None
    row.categories = {c["name"]: c["minutes"] for c in got.get("categories") or []} or None
    row.top_apps = [
        {"name": a["name"], "minutes": a["minutes"]} for a in got.get("top_apps") or []
    ] or None
    row.updated_at = datetime.utcnow()


@router.post("/api/screentime/import")
async def import_screentime(body: STImportIn) -> dict[str, Any]:
    """iOS スクリーンタイムのスクショ (複数可) を OCR して取り込む。"""
    from app.llm.screentime_ocr import extract_screentime

    images = list(body.images or [])
    if body.image_base64:
        images.append(STImage(image_base64=body.image_base64, media_type=body.media_type))
    if not images:
        raise HTTPException(status_code=422, detail="画像がありません")

    parsed = []
    for im in images:
        got = await extract_screentime(image_b64=im.image_base64, media_type=im.media_type)
        if got:
            parsed.append(got)
    if not parsed:
        raise HTTPException(status_code=422, detail="読み取れませんでした (LLM 未設定/読取不可の可能性)")
    with session_scope() as session:
        for got in parsed:
            _apply(session, got)
        session.flush()
    return await get_screentime()


def _to_dict(r: ScreenTimeSample) -> dict[str, Any]:
    return {
        "period_type": r.period_type,
        "period_start": r.period_start.isoformat(),
        "daily_min": r.daily_min,
        "total_min": r.total_min,
        "categories": r.categories or {},
        "top_apps": r.top_apps or [],
    }


@router.get("/api/screentime")
async def get_screentime(days: int = 30) -> dict[str, Any]:
    """直近の日サンプル + 最新週サンプル + 集計。"""
    since = datetime.now().date() - timedelta(days=days)
    with session_scope() as session:
        day_rows = session.execute(
            select(ScreenTimeSample).where(
                ScreenTimeSample.period_type == "day", ScreenTimeSample.period_start >= since
            ).order_by(ScreenTimeSample.period_start.desc())
        ).scalars().all()
        week_row = session.execute(
            select(ScreenTimeSample).where(ScreenTimeSample.period_type == "week")
            .order_by(ScreenTimeSample.period_start.desc()).limit(1)
        ).scalars().first()
        days_list = [_to_dict(r) for r in day_rows]
        week = _to_dict(week_row) if week_row else None
    summary = summarize(days_list, week)
    return {"summary": summary, "days": days_list, "week": week}
