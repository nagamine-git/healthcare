"""日次の主観チェックイン (気分/活力/ストレス/筋肉痛) の記録・取得 API。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import get_settings
from app.db import session_scope
from app.models import SubjectiveCheckin

router = APIRouter()


def _today() -> Any:
    return datetime.now(ZoneInfo(get_settings().app_tz)).date()


def _to_dict(row: SubjectiveCheckin) -> dict[str, Any]:
    return {
        "date": row.date.isoformat(),
        "mood": row.mood,
        "energy": row.energy,
        "stress": row.stress,
        "soreness": row.soreness,
        "note": row.note,
    }


class CheckinIn(BaseModel):
    mood: int | None = Field(default=None, ge=1, le=5)
    energy: int | None = Field(default=None, ge=1, le=5)
    stress: int | None = Field(default=None, ge=1, le=5)
    soreness: int | None = Field(default=None, ge=1, le=5)
    note: str | None = Field(default=None, max_length=500)
    date: str | None = None


@router.post("/api/checkin")
async def post_checkin(body: CheckinIn) -> dict[str, Any]:
    from datetime import date as date_type

    target = date_type.fromisoformat(body.date) if body.date else _today()
    with session_scope() as session:
        row = session.get(SubjectiveCheckin, target)
        if row is None:
            row = SubjectiveCheckin(date=target)
            session.add(row)
        # 指定されたフィールドだけ更新 (部分更新)
        for field in ("mood", "energy", "stress", "soreness", "note"):
            val = getattr(body, field)
            if val is not None:
                setattr(row, field, val)
        row.updated_at = datetime.now(UTC).replace(tzinfo=None)
    return await get_checkin()


@router.get("/api/checkin")
async def get_checkin(days: int = 14) -> dict[str, Any]:
    today = _today()
    since = today - timedelta(days=days)
    with session_scope() as session:
        rows = session.execute(
            select(SubjectiveCheckin)
            .where(SubjectiveCheckin.date >= since)
            .order_by(SubjectiveCheckin.date.desc())
        ).scalars().all()
        items = [_to_dict(r) for r in rows]
        today_row = next((it for it in items if it["date"] == today.isoformat()), None)
    return {"today": today_row, "items": items}
