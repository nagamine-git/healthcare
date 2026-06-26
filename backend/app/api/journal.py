"""今日の紙(手書きジャーナル)向けの補助 API。今は Google カレンダー予定の薄い読み出し。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

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
