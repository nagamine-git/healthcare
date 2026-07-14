"""PHQ-2 + GAD-2 メンタルスクリーニングの記録・状態取得 API。

心身の客観サインが下向きのとき、または一定間隔でチェックを促す (should_prompt)。
陽性/中等度以上は wellbeing_alerts 経由で「いまコレ」にも自動連携される。
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import get_settings
from app.db import session_scope
from app.models import MentalScreening
from app.scoring.mental import (
    GAD2_ITEMS,
    PHQ2_ITEMS,
    SCALE_OPTIONS,
    days_since_last,
    prompt_status,
    score_screening,
)

router = APIRouter()


def _today() -> date_type:
    return datetime.now(ZoneInfo(get_settings().app_tz)).date()


def _to_dict(row: MentalScreening) -> dict[str, Any]:
    r = score_screening(row.phq2_1, row.phq2_2, row.gad2_1, row.gad2_2)
    return {
        "id": row.id,
        "date": row.date.isoformat(),
        "ts": row.ts.isoformat() if row.ts else None,
        "phq2": r.phq2,
        "gad2": r.gad2,
        "phq4": r.phq4,
        "depression_positive": r.depression_positive,
        "anxiety_positive": r.anxiety_positive,
        "severity": r.severity,
        "severity_label": r.severity_label,
        "note": row.note,
    }


def _status(session: Any, today: date_type) -> dict[str, Any]:
    rows = session.execute(
        select(MentalScreening)
        .order_by(MentalScreening.date.desc(), MentalScreening.id.desc())
        .limit(30)
    ).scalars().all()
    history = [_to_dict(r) for r in rows]
    prompt = prompt_status(session, today)
    return {
        "due": prompt["due"],
        "reason": prompt["reason"],
        "urgency": prompt["urgency"],
        "days_since_last": days_since_last(session, today),
        "latest": history[0] if history else None,
        "history": history,
        "items": PHQ2_ITEMS + GAD2_ITEMS,
        "scale": SCALE_OPTIONS,
    }


class ScreenIn(BaseModel):
    phq2_1: int = Field(ge=0, le=3)
    phq2_2: int = Field(ge=0, le=3)
    gad2_1: int = Field(ge=0, le=3)
    gad2_2: int = Field(ge=0, le=3)
    note: str | None = Field(default=None, max_length=500)
    date: str | None = None


@router.post("/api/mental/screen")
async def post_screen(body: ScreenIn) -> dict[str, Any]:
    target = date_type.fromisoformat(body.date) if body.date else _today()
    r = score_screening(body.phq2_1, body.phq2_2, body.gad2_1, body.gad2_2)
    with session_scope() as session:
        session.add(MentalScreening(
            date=target, phq2_1=body.phq2_1, phq2_2=body.phq2_2,
            gad2_1=body.gad2_1, gad2_2=body.gad2_2,
            phq2=r.phq2, gad2=r.gad2, phq4=r.phq4, note=body.note,
        ))
        session.flush()
        return _status(session, _today())


@router.get("/api/mental")
async def get_mental() -> dict[str, Any]:
    with session_scope() as session:
        return _status(session, _today())
