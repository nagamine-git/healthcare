"""Garden(理想の庭)API。判定は scoring/garden に委譲し、ハンドラは薄く保つ。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import get_settings
from app.db import session_scope
from app.models.health import GardenConfig, GardenDaily, GoodActionLog
from app.scoring.garden.recompute import gaps_from_report, recompute_garden_for_date
from app.scoring.identity.store import build_gap_report
from app.scoring.timewindow import app_today

router = APIRouter()

_GRID_DAYS = 371  # 約53週


class GardenLogIn(BaseModel):
    kind: str
    note: str | None = None
    ts_iso: str | None = None


class GardenConfigIn(BaseModel):
    github_username: str | None = None
    github_token: str | None = None


def _today_payload(row: GardenDaily | None) -> dict:
    if row is None:
        return {"level": 0, "intensity": 0.0, "contributions": {}, "actions": []}
    contributions = row.contributions or {}
    return {
        "level": row.level,
        "intensity": row.intensity,
        "contributions": contributions,
        "actions": list(contributions.keys()),
    }


@router.get("/api/garden")
async def get_garden() -> dict:
    settings = get_settings()
    today = app_today()
    start = today - timedelta(days=_GRID_DAYS)
    with session_scope() as session:
        rows = (
            session.query(GardenDaily)
            .filter(GardenDaily.date >= start)
            .order_by(GardenDaily.date)
            .all()
        )
        grid = [
            {"date": r.date.isoformat(), "level": r.level,
             "intensity": r.intensity, "contributions": r.contributions or {}}
            for r in rows
        ]
        today_row = session.get(GardenDaily, today)
        streak = today_row.streak_len if today_row else 0

        report = build_gap_report(session)
        gaps = gaps_from_report(report)
        weakest_hint = None
        present = {k: v for k, v in gaps.items() if v is not None}
        if present:
            top_dim = max(present, key=present.get)
            kinds = [c["kind"] for c in settings.garden_catalog if top_dim in c["dimensions"]]
            dim_name = next(
                (d.get("name") for d in report.get("dimensions", []) if d["id"] == top_dim),
                top_dim,
            )
            if kinds:
                weakest_hint = {"dimension_id": top_dim, "name": dim_name, "kinds": kinds}

        cfg = session.get(GardenConfig, 1)
        github = {
            "connected": bool(cfg and cfg.github_token),
            "username": cfg.github_username if cfg else None,
        }
        catalog = [
            {"kind": c["kind"], "source": c["source"], "evidence": c["evidence"],
             "dimensions": c["dimensions"]}
            for c in settings.garden_catalog
        ]
        today_payload = _today_payload(today_row)

    return {
        "date": today.isoformat(),
        "grid": grid,
        "streak": streak,
        "today": today_payload,
        "catalog": catalog,
        "weakest_hint": weakest_hint,
        "github": github,
    }


@router.post("/api/garden/log")
async def add_garden_log(body: GardenLogIn) -> dict:
    if body.ts_iso:
        ts = datetime.fromisoformat(body.ts_iso)
        if ts.tzinfo is not None:
            ts = ts.astimezone(UTC).replace(tzinfo=None)
        target = ts.date()
    else:
        ts = datetime.now(UTC).replace(tzinfo=None)
        target = app_today()
    with session_scope() as session:
        session.add(
            GoodActionLog(ts=ts, kind=body.kind, source="manual", value=1.0, note=body.note)
        )
        session.flush()
        row = recompute_garden_for_date(session, target)
        payload = _today_payload(row)
    return {"today": payload}


@router.post("/api/garden/config")
async def set_garden_config(body: GardenConfigIn) -> dict:
    with session_scope() as session:
        cfg = session.get(GardenConfig, 1)
        if cfg is None:
            cfg = GardenConfig(id=1)
            session.add(cfg)
        cfg.github_username = body.github_username
        if body.github_token:
            cfg.github_token = body.github_token
        cfg.updated_at = datetime.utcnow()
        session.flush()
        connected = bool(cfg.github_token)
        username = cfg.github_username
    return {"connected": connected, "username": username}
