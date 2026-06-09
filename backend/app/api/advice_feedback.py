"""LLM 助言アクションへのフィードバック (完了 / 有用度) API。

「測るが効いたか検証しない」を閉じる outcome ループ。記録した評価は
LLM payload に還元され、提案の学習に使われる。
"""

from __future__ import annotations

from datetime import UTC, datetime
from datetime import date as date_type
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import get_settings
from app.db import session_scope
from app.models import AdviceFeedback

router = APIRouter()


def _today() -> date_type:
    return datetime.now(ZoneInfo(get_settings().app_tz)).date()


def feedback_map(target: date_type) -> dict[str, dict[str, Any]]:
    """指定日のフィードバックを action_key -> {done, rating} で返す。"""
    with session_scope() as session:
        rows = session.execute(
            select(AdviceFeedback).where(AdviceFeedback.date == target)
        ).scalars().all()
        return {r.action_key: {"done": r.done, "rating": r.rating} for r in rows}


class FeedbackIn(BaseModel):
    action_key: str = Field(min_length=1, max_length=200)
    done: bool | None = None
    rating: int | None = Field(default=None, ge=-1, le=1)
    category: str | None = None
    date: str | None = None


@router.post("/api/advice/feedback")
async def post_feedback(body: FeedbackIn) -> dict[str, Any]:
    target = date_type.fromisoformat(body.date) if body.date else _today()
    with session_scope() as session:
        row = session.get(AdviceFeedback, (target, body.action_key))
        if row is None:
            row = AdviceFeedback(date=target, action_key=body.action_key)
            session.add(row)
        if body.done is not None:
            row.done = body.done
        if body.rating is not None:
            row.rating = body.rating
        if body.category is not None:
            row.category = body.category
        row.updated_at = datetime.now(UTC).replace(tzinfo=None)
    return {"feedback": feedback_map(target)}
