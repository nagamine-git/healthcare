"""Becoming(三層フライホイール + 到達予測)API。ハンドラは薄く、計算は scoring/becoming へ。"""

from __future__ import annotations

from fastapi import APIRouter

from app.config import get_settings
from app.db import session_scope
from app.llm.becoming import generate_one_move
from app.scoring.becoming.snapshot import backfill_snapshots, build_becoming_report
from app.scoring.identity.dimensions import get_dimension

router = APIRouter()


def _kinds_for_dimension(dim_id: str | None) -> list[str]:
    if not dim_id:
        return []
    settings = get_settings()
    return [c["kind"] for c in settings.garden_catalog if dim_id in c["dimensions"]]


@router.get("/api/becoming")
async def get_becoming() -> dict:
    with session_scope() as session:
        report = build_becoming_report(session)
    # ボトルネック次元に名前を付与
    traj = report["trajectory"]
    dim = get_dimension(traj.get("bottleneck_dimension")) if traj.get("bottleneck_dimension") else None
    traj["bottleneck_name"] = dim.name_ja if dim else None
    for pd in traj.get("per_dimension", []):
        d = get_dimension(pd["id"])
        pd["name"] = d.name_ja if d else pd["id"]
    return report


@router.post("/api/becoming/one-move")
async def post_one_move() -> dict:
    with session_scope() as session:
        report = build_becoming_report(session)
    traj = report["trajectory"]
    bottleneck_id = traj.get("bottleneck_dimension")
    dim = get_dimension(bottleneck_id) if bottleneck_id else None
    history = report.get("history", [])
    condition = history[-1]["condition"] if history else None
    from app.api.checkup import latest_checkup_summary

    state = {
        "condition": condition,
        "diagnosis": report["loop_week"]["diagnosis"],
        "bottleneck_id": bottleneck_id,
        "bottleneck_name": dim.name_ja if dim else None,
        "bottleneck_desc": dim.description if dim else None,
        "kinds": _kinds_for_dimension(bottleneck_id),
        "checkup": latest_checkup_summary(),
    }
    move = await generate_one_move(state)
    if move is None:
        # LLM 未設定/失敗時の構造化フォールバック
        name = dim.name_ja if dim else "理想"
        move = {
            "move": f"{name}を前進させる行動を、今日ひとつ実行する。",
            "if_then": "退勤したら、まず10分その行動に着手する。",
            "dimension_id": bottleneck_id or "",
            "rationale": "盲点に効く行動の着手だけでも前進になる。",
            "fallback": True,
        }
    return move


@router.post("/api/becoming/backfill")
async def post_backfill() -> dict:
    with session_scope() as session:
        filled = backfill_snapshots(session, days=120)
    return {"filled": filled}
