"""就寝前の介入 (耳栓/アイマスク/鼻ストリップ/口テープ) の記録・分析 API。

夜次 upsert (date 主キー)。日付は SleepSession.date (起床日基準) に合わせる:
夜 (18:00 以降) に記録した介入は「今夜眠って明朝起きる」ので起床日=翌日に紐付ける。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from datetime import date as date_type
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import get_settings
from app.db import session_scope
from app.models import SleepInterventionLog
from app.scoring import sleep_interventions

router = APIRouter()

_FLAGS = ("earplugs", "eyemask", "nose_strip", "mouth_tape")


def _target_date() -> date_type:
    """記録対象の夜 (= その眠りの起床日)。夜 18:00 以降は翌朝が起床日。"""
    now = datetime.now(ZoneInfo(get_settings().app_tz))
    return now.date() + timedelta(days=1) if now.hour >= 18 else now.date()


def _to_dict(row: SleepInterventionLog | None, target: date_type) -> dict[str, Any]:
    # 「その夜」は起床日の前日夜。UI 表示用に M/D を付す。
    eve = target - timedelta(days=1)
    display = f"{eve.month}/{eve.day}の夜"
    if row is None:
        return {
            "date": target.isoformat(), "display_label": display,
            **{f: None for f in _FLAGS}, "note": None, "updated_at": None,
        }
    return {
        "date": row.date.isoformat(), "display_label": display,
        "earplugs": row.earplugs, "eyemask": row.eyemask,
        "nose_strip": row.nose_strip, "mouth_tape": row.mouth_tape,
        "note": row.note,
        "updated_at": (
            row.updated_at.replace(tzinfo=UTC).isoformat() if row.updated_at else None
        ),
    }


class InterventionIn(BaseModel):
    earplugs: bool | None = None
    eyemask: bool | None = None
    nose_strip: bool | None = None
    mouth_tape: bool | None = None
    note: str | None = Field(default=None, max_length=500)
    reset: bool = False  # その夜の記録を未記録 (全 None) に戻す
    date: str | None = None


@router.post("/api/sleep-intervention")
async def post_intervention(body: InterventionIn) -> dict[str, Any]:
    target = date_type.fromisoformat(body.date) if body.date else _target_date()
    with session_scope() as session:
        row = session.get(SleepInterventionLog, target)
        if row is None:
            row = SleepInterventionLog(date=target)
            session.add(row)
        if body.reset:
            for f in _FLAGS:
                setattr(row, f, None)
            row.note = None
        else:
            # None = 据え置き。フロントは通常 4 フラグ全部を明示 bool で送る。
            for f in _FLAGS:
                val = getattr(body, f)
                if val is not None:
                    setattr(row, f, val)
            if body.note is not None:
                row.note = body.note
        row.updated_at = datetime.now(UTC).replace(tzinfo=None)
    return await get_intervention()


@router.get("/api/sleep-intervention")
async def get_intervention(days: int = 30) -> dict[str, Any]:
    target = _target_date()
    since = target - timedelta(days=days)
    with session_scope() as session:
        rows = session.execute(
            select(SleepInterventionLog)
            .where(SleepInterventionLog.date >= since)
            .order_by(SleepInterventionLog.date.desc())
        ).scalars().all()
        tonight_row = next((r for r in rows if r.date == target), None)
        items = [_to_dict(r, r.date) for r in rows]
    return {"tonight": _to_dict(tonight_row, target), "items": items}


@router.get("/api/sleep/interventions")
async def get_intervention_analysis() -> dict[str, Any]:
    """各介入が睡眠の質を有意に改善するかの n-of-1 分析。"""
    return sleep_interventions.analyze()
