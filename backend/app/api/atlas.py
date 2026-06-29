"""メトリクス・アトラス(全体マップ)API。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.db import session_scope
from app.scoring.atlas import build_atlas

router = APIRouter()


@router.get("/api/atlas")
async def get_atlas() -> dict[str, Any]:
    with session_scope() as session:
        return {"tree": build_atlas(session)}
