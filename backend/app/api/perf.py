"""パフォーマンス監視の参照 API(debug 画面用)。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from app.db import session_scope
from app.models.health import PerfIssue
from app.perf import perf_tick_job, registry

router = APIRouter()


@router.get("/api/admin/perf")
async def get_perf() -> dict[str, Any]:
    # 直近の in-memory 分も DB に反映してから返す。
    await perf_tick_job()
    snap = registry.snapshot()
    with session_scope() as session:
        rows = session.execute(
            select(PerfIssue).order_by(PerfIssue.resolved, PerfIssue.last_ts.desc()).limit(100)
        ).scalars().all()
        issues = [
            {
                "id": r.id, "kind": r.kind, "label": r.label, "count": r.count,
                "max_duration_ms": round(r.max_duration_ms, 1), "detail": r.detail,
                "resolved": r.resolved, "last_ts": r.last_ts.isoformat(),
            }
            for r in rows
        ]
    return {"live": snap, "issues": issues}
