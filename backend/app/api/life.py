"""ライフドメインの達成度・重み・プリセット API。"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.config import get_settings
from app.db import session_scope
from app.models import DomainWeight
from app.scoring import domains as dom
from app.scoring.timewindow import app_today

router = APIRouter()


def _today() -> date:
    return app_today()


def _load_weights() -> dict[str, float]:
    with session_scope() as session:
        rows = session.execute(select(DomainWeight)).scalars().all()
        saved = {r.domain: r.weight for r in rows}
    # 未設定ドメインは既定 1.0
    return {key: saved.get(key, 1.0) for key, _, _ in dom.LIFE_DOMAINS}


def _save_weights(weights: dict[str, float]) -> None:
    with session_scope() as session:
        for domain, weight in weights.items():
            row = session.get(DomainWeight, domain)
            if row is None:
                session.add(DomainWeight(domain=domain, weight=float(weight)))
            else:
                row.weight = float(weight)


def _detail(key: str, target: date, weight: float = 1.0) -> str | None:
    if key == "meditation":
        m = dom.meditation_minutes(target)
        # 重み＝期待水準なので実効目標 (目標 × weight) を表示する
        tgt = get_settings().meditation_target_min * (weight if weight > 0 else 1.0)
        return f"{m:.0f}/{tgt:g}分" if m is not None else None
    if key == "speech":
        return "発話練習スコア (speech-coach)"
    if key == "health":
        return "6指標の達成度平均"
    if key in ("learning", "work"):
        from app.models import ExternalDomainEntry

        with session_scope() as session:
            row = session.get(ExternalDomainEntry, (key, target))
            return row.detail if row else None
    return None


def _state(target: date) -> dict[str, Any]:
    weights = _load_weights()
    life = dom.compute_life(target, weights)
    for d in life["domains"]:
        d["detail"] = _detail(d["key"], target, d["weight"])
        last = dom.domain_last_data(d["key"])
        d["last_data_at"] = last.isoformat() if last else None
        threshold = dom.STALE_AFTER_DAYS.get(d["key"], 7)
        d["stale"] = last is None or (target - last).days > threshold
    active_domains = [d for d in life["domains"] if d["weight"] > 0]
    coverage = {
        "active": sum(1 for d in active_domains if d["achievement"] is not None),
        "total": len(active_domains),
    }
    presets = [{"key": k, "label": v["label"]} for k, v in dom.DOMAIN_WEIGHT_PRESETS.items()]
    return {
        "life_score": life["life_score"],
        "domains": life["domains"],
        "coverage": coverage,
        "presets": presets,
        "generated_at": datetime.now(UTC).isoformat(),
    }


@router.get("/api/life")
async def get_life() -> dict[str, Any]:
    return _state(_today())


@router.get("/api/life/tree")
async def get_life_tree() -> dict[str, Any]:
    """4層モデル(目的→目標→ドメイン木)の集約。"""
    from app.scoring.life.tree import compute_life_tree

    with session_scope() as session:
        return compute_life_tree(session, app_today())


class WeightsIn(BaseModel):
    weights: dict[str, float]


@router.put("/api/life/weights")
async def put_weights(body: WeightsIn) -> dict[str, Any]:
    valid = {k for k, _, _ in dom.LIFE_DOMAINS}
    clean = {k: max(0.0, float(v)) for k, v in body.weights.items() if k in valid}
    _save_weights(clean)
    return _state(_today())


@router.post("/api/life/preset/{name}")
async def apply_preset(name: str) -> dict[str, Any]:
    preset = dom.DOMAIN_WEIGHT_PRESETS.get(name)
    if preset is None:
        raise HTTPException(status_code=404, detail="unknown preset")
    _save_weights(preset["weights"])
    return _state(_today())
