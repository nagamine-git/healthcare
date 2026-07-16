"""Airgap の浪費実測 × 睡眠/HRV の自己内相関インサイト (read-only)。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.db import session_scope
from app.scoring.airgap_insight import compute_airgap_sleep_insight, gather_airgap_sleep_rows
from app.scoring.timewindow import app_today

router = APIRouter()


@router.get("/api/airgap/insight")
async def get_airgap_insight() -> dict[str, Any]:
    with session_scope() as session:
        rows = gather_airgap_sleep_rows(session, app_today())
    return compute_airgap_sleep_insight(rows)
