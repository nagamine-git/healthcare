"""「いまコレ」API — 今この瞬間に最も価値のある行動を1つ返す (読み取り専用)。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.scoring.next_action import compute_next_action

router = APIRouter()


@router.get("/api/next-action")
async def get_next_action() -> dict[str, Any]:
    """全ドメイン横断の候補から、いまの最優先アクション + 次点を返す。"""
    return compute_next_action()
