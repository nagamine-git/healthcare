"""法人 (freee) 財務の参照 API。書き込みは /admin/freee/sync + oauth コールバック側。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.db import session_scope

router = APIRouter()


@router.get("/api/corporate-finance")
async def get_corporate_finance() -> dict[str, Any]:
    from app.integrations.freee_client import has_token
    from app.scoring.corporate_finance import compute_corporate_finance

    with session_scope() as session:
        data = compute_corporate_finance(session)
    return {"connected": has_token(), "data": data}
