"""メトリクス・アトラス(全体マップ)API。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.db import session_scope
from app.scoring.atlas import build_atlas

router = APIRouter()


@router.get("/api/atlas")
async def get_atlas() -> dict[str, Any]:
    # 開いた瞬間にほぼリアルタイムな総合点を見せる (直近120秒以内なら省略)。
    from app.scoring.recompute import ensure_today_fresh

    ensure_today_fresh()
    with session_scope() as session:
        return {"tree": build_atlas(session)}


class AtlasWeightIn(BaseModel):
    key: str
    weight: float


@router.put("/api/atlas/weight")
async def set_atlas_weight(body: AtlasWeightIn) -> dict[str, Any]:
    """任意ノード(末端まで)の優先の重みを設定。domain_weight テーブルを汎用 key→重み として使う。"""
    from app.models import DomainWeight

    with session_scope() as session:
        row = session.get(DomainWeight, body.key)
        w = max(0.0, min(5.0, body.weight))
        if row is None:
            session.add(DomainWeight(domain=body.key[:32], weight=w))
        else:
            row.weight = w
        session.flush()
        return {"tree": build_atlas(session)}
