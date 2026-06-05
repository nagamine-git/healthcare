"""学習・仕事など外部ライフドメインの日次達成度を取り込む汎用 API。"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.db import session_scope
from app.models import ExternalDomainEntry

router = APIRouter()

# 外部取り込み対象のドメイン (health/meditation/speech は専用ロジックなので含めない)。
_EXTERNAL = {"learning", "work"}


class DomainIngestIn(BaseModel):
    date: str  # YYYY-MM-DD
    achievement: float | None = None  # 0-100
    detail: str | None = None


@router.post("/api/domain/{key}/ingest")
async def ingest_domain(key: str, body: DomainIngestIn) -> dict[str, Any]:
    if key not in _EXTERNAL:
        raise HTTPException(status_code=404, detail=f"unknown external domain: {key}")
    d = date_type.fromisoformat(body.date)
    with session_scope() as session:
        row = session.get(ExternalDomainEntry, (key, d))
        if row is None:
            row = ExternalDomainEntry(domain=key, date=d)
            session.add(row)
        row.achievement = body.achievement
        row.detail = body.detail
    return {"status": "ok", "domain": key, "date": body.date}


@router.get("/api/domain/{key}")
async def list_domain(key: str, days: int = 28) -> dict[str, Any]:
    end = datetime.now().date()
    start = end - timedelta(days=days)
    with session_scope() as session:
        rows = session.execute(
            select(ExternalDomainEntry)
            .where(ExternalDomainEntry.domain == key, ExternalDomainEntry.date >= start)
            .order_by(ExternalDomainEntry.date)
        ).scalars().all()
        data = [
            {"date": r.date.isoformat(), "achievement": r.achievement, "detail": r.detail}
            for r in rows
        ]
    return {"domain": key, "data": data}
