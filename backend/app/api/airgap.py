"""Airgap アプリ (スマホデトックス) からの日次生産性スコア ingest。

HAE と同じ Bearer トークン (HAE_INGEST_TOKEN) で認証し、日付 upsert。
"""

from __future__ import annotations

from datetime import UTC, datetime
from datetime import date as date_type
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.db import session_scope
from app.models import AirgapDaily

router = APIRouter()


def _verify_token(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    expected = settings.hae_ingest_token
    if not expected:
        raise HTTPException(status_code=500, detail="HAE_INGEST_TOKEN is not configured.")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required.")
    if authorization.split(" ", 1)[1].strip() != expected:
        raise HTTPException(status_code=401, detail="Invalid token.")


class AirgapReportIn(BaseModel):
    date: str
    score: int = Field(ge=0, le=100)
    completed_min: int = Field(ge=0)
    failures: int = Field(ge=0)
    goal_min: int = Field(gt=0)
    waste_min: int | None = Field(default=None, ge=0)
    waste_limit_min: int = Field(gt=0)
    sessions: int = Field(ge=0)
    source: str = "airgap"


@router.post("/ingest/airgap", status_code=status.HTTP_202_ACCEPTED)
async def ingest_airgap(
    body: AirgapReportIn, _: None = Depends(_verify_token)
) -> dict[str, Any]:
    day = date_type.fromisoformat(body.date)
    with session_scope() as session:
        row = session.get(AirgapDaily, day)
        if row is None:
            row = AirgapDaily(date=day, score=body.score)
            session.add(row)
        row.score = body.score
        row.completed_min = body.completed_min
        row.failures = body.failures
        row.goal_min = body.goal_min
        row.waste_min = body.waste_min
        row.waste_limit_min = body.waste_limit_min
        row.sessions = body.sessions
        row.updated_at = datetime.now(UTC).replace(tzinfo=None)
    return {"status": "ok", "date": body.date, "score": body.score}
