"""今日の紙(手書きジャーナル)向けの補助 API。今は Google カレンダー予定の薄い読み出し。"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import get_settings
from app.db import session_scope
from app.llm.journal_extract import extract_actions
from app.llm.journal_ocr import transcribe_journal
from app.models.health import GoodActionLog, JournalEntry
from app.scoring.garden.recompute import recompute_garden_for_date
from app.scoring.timewindow import app_today, jst_day_bounds

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


class ExtractIn(BaseModel):
    text: str
    date: str | None = None


@router.post("/api/journal/extract")
async def extract_entry(body: ExtractIn) -> dict[str, Any]:
    """控えテキストから『やった良い行動』を保守的に抽出して提案(記録はしない)。"""
    d = date_type.fromisoformat(body.date) if body.date else app_today()
    catalog = [
        {"kind": c["kind"], "label": c.get("evidence", c["kind"])}
        for c in get_settings().garden_catalog
    ]
    actions = await extract_actions(body.text, catalog)
    if not actions:
        return {"proposals": []}
    with session_scope() as session:
        logged = _logged_kinds_on(session, d)
    proposals = [
        {
            "kind": a["kind"],
            "evidence": a.get("evidence", ""),
            "confidence": a.get("confidence", "med"),
            "already_logged": a["kind"] in logged,
        }
        for a in actions
    ]
    return {"proposals": proposals}


class ExtractCommitIn(BaseModel):
    kinds: list[str]
    date: str | None = None


@router.post("/api/journal/extract/commit")
async def extract_commit(body: ExtractCommitIn) -> dict[str, Any]:
    """確認済みの行動をその日付にバックフィル(冪等)。"""
    d = date_type.fromisoformat(body.date) if body.date else app_today()
    allowed = {c["kind"] for c in get_settings().garden_catalog}
    logged: list[str] = []
    with session_scope() as session:
        for k in body.kinds:
            if k in allowed and _log_extracted_action(session, d, k):
                logged.append(k)
        session.flush()
        if logged:
            recompute_garden_for_date(session, d)
    return {"logged": logged}


class EntryIn(BaseModel):
    text: str
    date: str | None = None
    source: str = "text"


def _logged_kinds_on(session, d: date_type) -> set[str]:
    """その日(JST)に既に記録済みの行動 kind 集合(手動チップ・自動取込含む)。

    journaling は控え(JournalEntry)の存在で判定する(GoodActionLog は作らない)。
    """
    start, end = jst_day_bounds(d)
    kinds = {
        k for (k,) in session.query(GoodActionLog.kind)
        .filter(GoodActionLog.ts >= start, GoodActionLog.ts < end).all()
    }
    if session.get(JournalEntry, d) is not None:
        kinds.add("journaling")
    return kinds


def _log_extracted_action(session, d: date_type, kind: str) -> bool:
    """控えから抽出した行動をその日付に記録。同日・同 kind が既にあればスキップ(False)。"""
    if kind in _logged_kinds_on(session, d):
        return False
    start, _ = jst_day_bounds(d)
    session.add(
        GoodActionLog(
            ts=start + timedelta(hours=12), kind=kind, source="journal", value=1.0,
            dedup_key=f"journal-extract:{d.isoformat()}:{kind}", note="控えから抽出",
        )
    )
    return True


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
        created = row.text is None
        row.text = body.text[:8000]
        row.source = body.source
        row.updated_at = datetime.utcnow()
        session.flush()
        # 控えの存在 = その日のジャーナリング実施(JournalEntry が source of truth)。
        # 庭を再計算して journaling を反映(控えを消せば次の再計算で外れる)。
        recompute_garden_for_date(session, d)
        return {"entries": _entries(session), "journaling_logged": created}


@router.delete("/api/journal/entry/{entry_date}")
async def delete_entry(entry_date: str) -> dict[str, Any]:
    with session_scope() as session:
        d = date_type.fromisoformat(entry_date)
        row = session.get(JournalEntry, d)
        if row is None:
            raise HTTPException(status_code=404, detail="not found")
        session.delete(row)
        session.flush()
        # 控えが消えたら journaling も外れる(庭を再計算して反映)。
        recompute_garden_for_date(session, d)
        return {"entries": _entries(session)}
