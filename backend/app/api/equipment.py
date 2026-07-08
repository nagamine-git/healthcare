"""器具 CRUD — トレ処方が使ってよい機材を DB で管理 (空なら settings からシード)。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db import session_scope
from app.models import EquipmentItem
from app.scoring.equipment import resolve_equipment

router = APIRouter()


def _list() -> list[dict[str, Any]]:
    with session_scope() as s:
        rows = s.execute(
            select(EquipmentItem).order_by(EquipmentItem.sort, EquipmentItem.id)
        ).scalars().all()
        return [
            {"id": r.id, "name": r.name, "available": r.available, "note": r.note}
            for r in rows
        ]


@router.get("/api/equipment")
async def get_equipment() -> dict[str, Any]:
    resolve_equipment()  # 空ならシード
    return {"items": _list()}


class EquipmentIn(BaseModel):
    id: int | None = None
    name: str = Field(max_length=120)
    available: bool = True
    note: str | None = Field(default=None, max_length=200)


@router.post("/api/equipment")
async def upsert_equipment(body: EquipmentIn) -> dict[str, Any]:
    with session_scope() as s:
        row = s.get(EquipmentItem, body.id) if body.id else None
        if row is None:
            row = EquipmentItem(name=body.name)
            s.add(row)
        row.name = body.name
        row.available = body.available
        row.note = body.note
        s.flush()
    return {"items": _list()}


@router.delete("/api/equipment/{item_id}")
async def delete_equipment(item_id: int) -> dict[str, Any]:
    with session_scope() as s:
        row = s.get(EquipmentItem, item_id)
        if row is None:
            raise HTTPException(status_code=404, detail="not found")
        s.delete(row)
    return {"items": _list()}
