from __future__ import annotations

from datetime import date as date_type
from typing import Any

from fastapi import APIRouter, HTTPException, status

router = APIRouter()


@router.post("/admin/recompute")
async def recompute(target: date_type | None = None) -> dict[str, Any]:
    from app.scoring.recompute import recompute_for_date

    d = target or date_type.today()
    result = recompute_for_date(d)
    return {"date": d.isoformat(), "result": result}


@router.post("/admin/garmin/sync")
async def garmin_sync() -> dict[str, Any]:
    from app.ingest.garmin_sync import sync_garmin_job

    try:
        result = await sync_garmin_job()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Garmin sync failed: {exc}"
        ) from exc
    return {"result": result}


@router.post("/admin/llm/regenerate")
async def llm_regenerate(target: date_type | None = None) -> dict[str, Any]:
    from app.llm.client import generate_advice_for_date

    d = target or date_type.today()
    comment = await generate_advice_for_date(d, force=True)
    return {"date": d.isoformat(), "comment": comment}


@router.get("/admin/gcal/status")
async def gcal_status() -> dict[str, Any]:
    from app.integrations.gcal import client_secret_path, has_token, load_credentials

    cs_exists = client_secret_path().exists()
    if not cs_exists:
        return {"configured": False, "reason": "client_secret.json missing"}
    if not has_token():
        return {"configured": False, "reason": "token.json missing — run gcal-login"}
    creds = load_credentials()
    if creds is None:
        return {"configured": False, "reason": "credentials invalid — re-run gcal-login"}
    return {"configured": True}


@router.post("/admin/gcal/schedule")
async def gcal_schedule(target: date_type | None = None) -> dict[str, Any]:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from sqlalchemy import select

    from app.db import session_scope
    from app.integrations.gcal import (
        schedule_actions_from_comment,
        schedule_actions_from_payload,
    )
    from app.models import LlmComment

    d = target or date_type.today()
    with session_scope() as session:
        latest = session.execute(
            select(LlmComment)
            .where(LlmComment.date == d)
            .order_by(LlmComment.generated_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        comment_text = latest.comment if latest else None
        payload = latest.payload if latest else None

    if not comment_text and not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="アドバイスがまだ生成されていません。先に LLM 再生成を実行してください。",
        )

    now_jst = datetime.now(ZoneInfo("Asia/Tokyo"))
    try:
        # 同日の Healthcare 管理イベントを先に削除 (重複防止 + リプレース)
        from app.integrations.gcal import delete_managed_events_for_date

        deleted = delete_managed_events_for_date(d)

        if payload and isinstance(payload, dict) and payload.get("actions"):
            created = schedule_actions_from_payload(payload, target_date=now_jst)
        else:
            created = schedule_actions_from_comment(comment_text or "", target_date=now_jst)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Google Calendar 連携でエラー: {exc}",
        ) from exc
    return {"date": d.isoformat(), "deleted": deleted, "created": created}
