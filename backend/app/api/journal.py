"""今日の紙(手書きジャーナル)向けの補助 API。今は Google カレンダー予定の薄い読み出し。"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db import session_scope
from app.llm.journal_ocr import transcribe_journal
from app.models.health import JournalEntry
from app.scoring.timewindow import app_today

router = APIRouter()


@router.get("/api/journal/calendar")
async def journal_calendar() -> dict[str, Any]:
    """今日(JST)の予定を時刻つきで返す。認証なし/未連携なら空。"""
    from app.integrations.gcal import list_events_for_date

    events: list[dict[str, Any]] = []
    for e in list_events_for_date(app_today()):
        start = e.get("start") or ""
        # ISO "....T09:00:00+09:00" → 時/分
        try:
            hh = int(start[11:13])
            mm = int(start[14:16])
        except (ValueError, IndexError):
            continue
        events.append({
            "hour": hh,
            "minute": mm,
            "summary": e.get("summary", ""),
            "busy": bool(e.get("is_busy", True)),
        })
    return {"events": events}


class TranscribeIn(BaseModel):
    image_base64: str
    media_type: str = "image/png"


@router.post("/api/journal/transcribe")
async def journal_transcribe(body: TranscribeIn) -> dict[str, Any]:
    """写真を文字起こしして下書きを返す(保存はしない。確認・修正用)。"""
    text = await transcribe_journal(image_b64=body.image_base64, media_type=body.media_type)
    if text is None:
        raise HTTPException(status_code=502, detail="文字起こしに失敗(LLM 未設定または読取不可)")
    return {"text": text}


class EntryIn(BaseModel):
    text: str
    date: str | None = None
    source: str = "text"


def _entries(session) -> list[dict[str, Any]]:
    return [
        {"date": r.date.isoformat(), "text": r.text, "source": r.source}
        for r in session.query(JournalEntry).order_by(JournalEntry.date.desc()).limit(60).all()
    ]


@router.get("/api/journal/entries")
async def get_entries() -> dict[str, Any]:
    with session_scope() as session:
        return {"entries": _entries(session)}


@router.put("/api/journal/entry")
async def put_entry(body: EntryIn) -> dict[str, Any]:
    """日付ごとに1件 upsert(確認・修正後のテキストを保存)。"""
    d = date_type.fromisoformat(body.date) if body.date else app_today()
    with session_scope() as session:
        row = session.get(JournalEntry, d)
        if row is None:
            row = JournalEntry(date=d)
            session.add(row)
        row.text = body.text[:8000]
        row.source = body.source
        row.updated_at = datetime.utcnow()
        session.flush()
        return {"entries": _entries(session)}


@router.delete("/api/journal/entry/{entry_date}")
async def delete_entry(entry_date: str) -> dict[str, Any]:
    with session_scope() as session:
        row = session.get(JournalEntry, date_type.fromisoformat(entry_date))
        if row is None:
            raise HTTPException(status_code=404, detail="not found")
        session.delete(row)
        session.flush()
        return {"entries": _entries(session)}
