from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, status

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


def _recompute_today_after_ingest() -> None:
    """取り込んだ新データを即スコアに反映 (レスポンス後にバックグラウンド実行)。"""
    from app.scoring.recompute import ensure_today_fresh

    # ingest 直後は必ず反映したいのでスロットルを 0 にして強制再計算。
    ensure_today_fresh(min_interval_s=0)


@router.post("/ingest/health-auto-export", status_code=status.HTTP_202_ACCEPTED)
async def ingest_health_auto_export(
    payload: dict[str, Any], background: BackgroundTasks, _: None = Depends(_verify_token)
) -> dict[str, Any]:
    parsed = parse_payload(payload)
    with session_scope() as session:
        counts = write_parse_result(session, parsed)
    # 新データ到着 → 今日の総合点を再計算 (HealthKit は変化時同期なので near-real-time)
    background.add_task(_recompute_today_after_ingest)
    return {"status": "ok", "counts": counts}
