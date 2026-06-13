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


class SectionCheckIn(BaseModel):
    field: Literal["read", "rustlings", "explained"]
    done: bool = True
    done_at_iso: str | None = None  # 過去の学習を記録する場合 (例 6/13 14:30)


@router.post("/api/learning/section/{section_id}/check")
async def check_section(section_id: str, body: SectionCheckIn) -> dict[str, Any]:
    try:
        return learning.set_section_check(
            section_id, body.field, body.done, done_at_iso=body.done_at_iso
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


class ActivityIn(BaseModel):
    detail: str | None = None


@router.post("/api/learning/activity")
async def record_activity(body: ActivityIn) -> dict[str, Any]:
    return learning.record_activity(body.detail)


class PlanIn(BaseModel):
    started_on: str | None = None  # YYYY-MM-DD
    target_date: str | None = None
    clear_started: bool = False
    clear_target: bool = False


@router.post("/api/learning/plan")
async def set_plan(body: PlanIn) -> dict[str, Any]:
    try:
        return learning.set_plan(
            started_on=body.started_on, target_date=body.target_date,
            clear_started=body.clear_started, clear_target=body.clear_target,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
