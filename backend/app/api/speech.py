"""speech-coach から発話練習の日次サマリを取り込む API。"""

from __future__ import annotations

from datetime import date as date_type
from datetime import timedelta
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from app.db import session_scope
from app.models import SpeechSession
from app.scoring.timewindow import app_today

router = APIRouter()


class SpeechIngestIn(BaseModel):
    date: str  # YYYY-MM-DD (JST)
    session_count: int = 0
    duration_min: float | None = None
    score_overall: float | None = None
    score_pace: float | None = None
    score_pitch: float | None = None
    score_clarity: float | None = None
    score_filler: float | None = None


def _to_dict(r: SpeechSession) -> dict[str, Any]:
    return {
        "date": r.date.isoformat(),
        "session_count": r.session_count,
        "duration_min": r.duration_min,
        "score_overall": r.score_overall,
        "score_pace": r.score_pace,
        "score_pitch": r.score_pitch,
        "score_clarity": r.score_clarity,
        "score_filler": r.score_filler,
    }


@router.post("/api/speech/ingest")
async def ingest_speech(body: SpeechIngestIn) -> dict[str, Any]:
    """speech-coach の日次サマリを upsert する。"""
    d = date_type.fromisoformat(body.date)
    with session_scope() as session:
        row = session.get(SpeechSession, d)
        if row is None:
            row = SpeechSession(date=d)
            session.add(row)
        row.session_count = body.session_count
        row.duration_min = body.duration_min
        row.score_overall = body.score_overall
        row.score_pace = body.score_pace
        row.score_pitch = body.score_pitch
        row.score_clarity = body.score_clarity
        row.score_filler = body.score_filler
    return {"status": "ok", "date": body.date}


@router.get("/api/speech")
async def list_speech(days: int = 28) -> dict[str, Any]:
    end = app_today()
    start = end - timedelta(days=days)
    with session_scope() as session:
        rows = session.execute(
            select(SpeechSession)
            .where(SpeechSession.date >= start)
            .order_by(SpeechSession.date)
        ).scalars().all()
        data = [_to_dict(r) for r in rows]
    return {"data": data}
