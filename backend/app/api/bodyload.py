"""部位別 (5 機能群) の刺激・回復・週間負荷 API。

スコアリングは app.scoring.bodyload に委譲し、ここは HTTP 層のみ。
データは既存 Workout (Garmin activity) から完全自動で導出する読み取り専用。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.scoring import bodyload

router = APIRouter()


@router.get("/api/bodyload")
async def get_bodyload() -> dict[str, Any]:
    return bodyload.state()
