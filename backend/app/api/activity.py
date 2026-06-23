"""活動/外出シグナル API。

全ソース (Garmin / iPhone Apple Health) を相互補完して日次の「動いた・外出した」を
推測した結果を返す。ロジックは scoring/activity_signal に集約。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.scoring.activity_signal import recent_signals

router = APIRouter()


@router.get("/api/activity/signal")
async def get_activity_signal(days: int = 14) -> dict[str, Any]:
    days = max(1, min(days, 60))
    return {"days": recent_signals(days)}
