from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.config import Settings, get_settings
from app.db import session_scope
from app.ingest.hae_parser import parse_payload
from app.ingest.hae_writer import write_parse_result

router = APIRouter()


def _verify_token(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    expected = settings.hae_ingest_token
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="HAE_INGEST_TOKEN is not configured.",
        )
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required.")
    token = authorization.split(" ", 1)[1].strip()
    if token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.")


@router.post("/ingest/health-auto-export", status_code=status.HTTP_202_ACCEPTED)
async def ingest_health_auto_export(payload: dict[str, Any], _: None = Depends(_verify_token)) -> dict[str, Any]:
    parsed = parse_payload(payload)
    with session_scope() as session:
        counts = write_parse_result(session, parsed)
    return {"status": "ok", "counts": counts}
