"""今日の予定 (Google Calendar 読み取り専用) API。

「今日」サーフェスの一部として、固定の予定を いまコレ/アラート と並べて見せる。
書き込みは admin/gcal/schedule 側。ここは read only で副作用なし。
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter

from app.config import get_settings

router = APIRouter()


def _now_tz() -> datetime:
    return datetime.now(ZoneInfo(get_settings().app_tz))


@router.get("/api/schedule/today")
async def schedule_today() -> dict[str, Any]:
    """今日 (JST) の予定一覧。未連携時は configured=false・events=[] を返す。"""
    from app.integrations.gcal import list_events_for_date, load_credentials

    tz = get_settings().app_tz
    now = _now_tz()
    today: date_type = now.date()
    if load_credentials() is None:
        return {"configured": False, "date": today.isoformat(), "now": now.isoformat(), "events": []}

    events = []
    for ev in list_events_for_date(today, timezone=tz):
        try:
            end_dt = datetime.fromisoformat(ev["end"])
        except (ValueError, KeyError, TypeError):
            end_dt = None
        # 終了済みの予定は「これから」の意思決定に不要なので落とす。
        past = end_dt is not None and end_dt < now
        events.append({
            "id": ev.get("id"),
            "title": ev.get("summary") or "(予定)",
            "start": ev.get("start"),
            "end": ev.get("end"),
            "is_busy": ev.get("is_busy", True),
            "is_hc_managed": ev.get("is_hc_managed", False),
            "past": past,
        })
    return {"configured": True, "date": today.isoformat(), "now": now.isoformat(), "events": events}
