"""Garden の scheduler ジョブ。"""

from __future__ import annotations

from app.db import session_scope
from app.logging import get_logger
from app.scoring.garden.recompute import recompute_garden_for_date
from app.scoring.timewindow import app_today

logger = get_logger(__name__)


async def garden_recompute_job() -> dict:
    today = app_today()
    with session_scope() as session:
        row = recompute_garden_for_date(session, today)
        result = {
            "status": "ok",
            "date": today.isoformat(),
            "level": row.level,
            "intensity": row.intensity,
            "streak": row.streak_len,
        }
    logger.info("garden_recompute_done", **result)
    return result
