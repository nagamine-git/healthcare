"""The Rust Book 完走プランの進捗 API。

カリキュラム・状態計算は app.scoring.learning に委譲し、ここは HTTP 層のみ。
journey リポジトリの git hook からは POST /api/learning/activity を叩く。
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.scoring import learning

router = APIRouter()


@router.get("/api/learning/state")
async def learning_state() -> dict[str, Any]:
    return learning.state()


class CheckIn(BaseModel):
    field: Literal["read", "rustlings", "explained"]
    done: bool = True


@router.post("/api/learning/chapter/{chapter}/check")
async def check_chapter(chapter: int, body: CheckIn) -> dict[str, Any]:
    try:
        return learning.set_check(chapter, body.field, body.done)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


class ActivityIn(BaseModel):
    detail: str | None = None


@router.post("/api/learning/activity")
async def record_activity(body: ActivityIn) -> dict[str, Any]:
    return learning.record_activity(body.detail)
