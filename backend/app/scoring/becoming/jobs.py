"""Becoming の scheduler ジョブ。"""

from __future__ import annotations

from app.db import session_scope
from app.logging import get_logger
from app.scoring.becoming.snapshot import capture_snapshot
from app.scoring.timewindow import app_today

logger = get_logger(__name__)


async def becoming_snapshot_job() -> dict:
    today = app_today()
    with session_scope() as session:
        row = capture_snapshot(session, today)
        result = {"status": "ok", "date": today.isoformat(), "condition": row.condition}
    logger.info("becoming_snapshot_done", **result)
    return result
