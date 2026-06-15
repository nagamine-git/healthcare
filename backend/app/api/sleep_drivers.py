"""個人「睡眠ドライバー分析」API (読み取り専用)。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.scoring import sleep_drivers

router = APIRouter()


@router.get("/api/sleep/drivers")
async def get_sleep_drivers() -> dict[str, Any]:
    """何が睡眠の質・翌日パフォーマンスを上げ下げするかの統計分析。"""
    return sleep_drivers.analyze()
