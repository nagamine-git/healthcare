"""偏頭痛エピソード (痛くなった/治った) を記録する API。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import get_settings
from app.db import session_scope
from app.models import MigraineEpisode

router = APIRouter()


class MigraineStartIn(BaseModel):
    severity: int | None = Field(default=None, ge=1, le=10)
    note: str | None = None
    ts_iso: str | None = None


class MigraineEndIn(BaseModel):
    note: str | None = None
    ts_iso: str | None = None


class MigraineEpisodeOut(BaseModel):
    id: int
    started_at: str
    started_at_jst: str
    ended_at: str | None
    ended_at_jst: str | None
    duration_min: int | None
    severity: int | None
    note: str | None
    active: bool


@router.post("/api/migraine/start", response_model=MigraineEpisodeOut)
async def start_migraine(body: MigraineStartIn) -> MigraineEpisodeOut:
    """新規エピソードを開始する。既に active なエピソードがある場合は 409。"""
    settings = get_settings()
    ts_utc = _resolve_ts(body.ts_iso)

    with session_scope() as session:
        active = _find_active(session)
        if active is not None:
            raise HTTPException(
                status_code=409,
                detail=f"active episode #{active.id} がまだ終了していません",
            )
        row = MigraineEpisode(
            started_at=ts_utc,
            ended_at=None,
            severity=body.severity,
            note=body.note,
        )
        session.add(row)
        session.flush()
        return _to_out(row, settings.app_tz)


@router.post("/api/migraine/end", response_model=MigraineEpisodeOut)
async def end_migraine(body: MigraineEndIn) -> MigraineEpisodeOut:
    """active エピソードを終了する。"""
    settings = get_settings()
    ts_utc = _resolve_ts(body.ts_iso)

    with session_scope() as session:
        active = _find_active(session)
        if active is None:
            raise HTTPException(status_code=404, detail="active episode が見つかりません")
        if ts_utc < active.started_at:
            raise HTTPException(
                status_code=400, detail="ended_at は started_at より後である必要があります"
            )
        active.ended_at = ts_utc
        if body.note:
            # 既存 note との連結 (デバッグ補助)
            active.note = (
                f"{active.note}\n{body.note}" if active.note else body.note
            )
        return _to_out(active, settings.app_tz)


@router.get("/api/migraine")
async def list_migraine(days: int = 30) -> dict[str, Any]:
    """直近 N 日のエピソード履歴と、現在の active を返す。"""
    settings = get_settings()
    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)
    with session_scope() as session:
        rows = session.execute(
            select(MigraineEpisode)
            .where(MigraineEpisode.started_at >= since)
            .order_by(MigraineEpisode.started_at.desc())
        ).scalars().all()
        items = [_to_out(r, settings.app_tz).model_dump() for r in rows]
        active = next((it for it in items if it["active"]), None)
        return {
            "items": items,
            "active": active,
            "count_30d": sum(1 for it in items if not it["active"]),
        }


class MigrainePatch(BaseModel):
    """編集用。指定したフィールドだけ更新する。"""

    started_at_iso: str | None = None
    ended_at_iso: str | None = None  # 空文字で再 active 化したい場合は別 API で
    severity: int | None = Field(default=None, ge=1, le=10)
    note: str | None = None
    clear_ended_at: bool = False  # True で ended_at を None に戻す (再 active 化)


@router.patch("/api/migraine/{episode_id}", response_model=MigraineEpisodeOut)
async def patch_migraine(
    episode_id: int, body: MigrainePatch
) -> MigraineEpisodeOut:
    settings = get_settings()
    with session_scope() as session:
        row = session.get(MigraineEpisode, episode_id)
        if row is None:
            raise HTTPException(status_code=404, detail="not found")

        if body.started_at_iso is not None:
            row.started_at = _resolve_ts(body.started_at_iso)

        if body.clear_ended_at:
            row.ended_at = None
        elif body.ended_at_iso is not None:
            new_end = _resolve_ts(body.ended_at_iso)
            if new_end < row.started_at:
                raise HTTPException(
                    status_code=400,
                    detail="ended_at は started_at より後である必要があります",
                )
            row.ended_at = new_end

        if body.severity is not None:
            row.severity = body.severity

        if body.note is not None:
            row.note = body.note or None

        session.flush()
        return _to_out(row, settings.app_tz)


@router.delete("/api/migraine/{episode_id}")
async def delete_migraine(episode_id: int) -> dict[str, Any]:
    with session_scope() as session:
        row = session.get(MigraineEpisode, episode_id)
        if row is None:
            raise HTTPException(status_code=404, detail="not found")
        session.delete(row)
        return {"deleted": episode_id}


def _resolve_ts(ts_iso: str | None) -> datetime:
    if not ts_iso:
        return datetime.now(UTC).replace(tzinfo=None)
    try:
        dt = datetime.fromisoformat(ts_iso)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid ts_iso: {exc}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).replace(tzinfo=None)


def _find_active(session) -> MigraineEpisode | None:
    return session.execute(
        select(MigraineEpisode)
        .where(MigraineEpisode.ended_at.is_(None))
        .order_by(MigraineEpisode.started_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _to_out(row: MigraineEpisode, tz_name: str) -> MigraineEpisodeOut:
    tz = ZoneInfo(tz_name)
    started_utc = (
        row.started_at.replace(tzinfo=UTC) if row.started_at.tzinfo is None else row.started_at
    )
    ended_utc = None
    if row.ended_at is not None:
        ended_utc = (
            row.ended_at.replace(tzinfo=UTC) if row.ended_at.tzinfo is None else row.ended_at
        )
    duration_min = None
    if ended_utc is not None:
        duration_min = int((ended_utc - started_utc).total_seconds() / 60)
    return MigraineEpisodeOut(
        id=row.id,
        started_at=started_utc.isoformat(),
        started_at_jst=started_utc.astimezone(tz).strftime("%m/%d %H:%M"),
        ended_at=ended_utc.isoformat() if ended_utc else None,
        ended_at_jst=(
            ended_utc.astimezone(tz).strftime("%m/%d %H:%M") if ended_utc else None
        ),
        duration_min=duration_min,
        severity=row.severity,
        note=row.note,
        active=row.ended_at is None,
    )
