"""その夜だけの起床時刻オーバーライド。

「明日は 5:30 に起きたい」を日単位で指定する。恒久の既定値は ``profile.wake_time``
(設定タブ) で、ここはそれを **その日だけ** 上書きする。

適用は ``scoring/sleep_plan.py:compute_tonight_plan()`` の 1 箇所だけ。そこが
wind_down / meditation / next_action / 通知 / LLM 助言など 11 モジュールに読まれるので、
起床時刻を差し替えれば就寝・入浴・夕食・カフェイン締切・呼吸法の判定・通知タイミングが
すべて自動で追随する (各モジュールへの個別対応は要らない)。

``date`` は **起床する日** (就寝日ではない)。日付キーなので過ぎれば自然に効かなくなる。
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.db import session_scope
from app.models import SleepPlanOverride
from app.scoring.timewindow import app_today

router = APIRouter()

_HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


class OverrideIn(BaseModel):
    date: date_type
    # 既存の profile API と同じ検証パターン
    wake_time: str = Field(pattern=_HHMM)


def _to_out(row: SleepPlanOverride) -> dict[str, Any]:
    return {"date": row.date.isoformat(), "wake_time": row.wake_time}


@router.get("/api/sleep-plan/override")
def get_override(date: date_type | None = Query(default=None)) -> dict[str, Any]:
    """指定日 (既定は今日) の上書き。無ければ ``{"override": null}``。"""
    d = date or app_today()
    with session_scope() as s:
        row = s.execute(
            select(SleepPlanOverride).where(SleepPlanOverride.date == d)
        ).scalar_one_or_none()
        return {"override": _to_out(row) if row is not None else None}


@router.put("/api/sleep-plan/override")
def put_override(body: OverrideIn) -> dict[str, Any]:
    """その日の起床時刻を上書き (upsert)。"""
    with session_scope() as s:
        row = s.execute(
            select(SleepPlanOverride).where(SleepPlanOverride.date == body.date)
        ).scalar_one_or_none()
        if row is None:
            row = SleepPlanOverride(date=body.date)
            s.add(row)
        row.wake_time = body.wake_time
        row.updated_at = datetime.utcnow()
        s.flush()
        return {"ok": True, "override": {"date": body.date.isoformat(), "wake_time": body.wake_time}}


@router.delete("/api/sleep-plan/override", status_code=status.HTTP_200_OK)
def delete_override(date: date_type | None = Query(default=None)) -> dict[str, Any]:
    """上書きを消して既定値 (profile.wake_time) に戻す。無くてもエラーにしない (冪等)。"""
    d = date or app_today()
    with session_scope() as s:
        n = s.execute(delete(SleepPlanOverride).where(SleepPlanOverride.date == d)).rowcount
    return {"ok": True, "deleted": int(n or 0)}


@router.get("/api/sleep-plan/override/upcoming")
def list_upcoming() -> dict[str, Any]:
    """今日以降の上書き一覧 (UI で「予約済み」を出すため)。"""
    today = app_today()
    with session_scope() as s:
        rows = s.execute(
            select(SleepPlanOverride)
            .where(SleepPlanOverride.date >= today)
            .order_by(SleepPlanOverride.date)
        ).scalars().all()
        return {"items": [_to_out(r) for r in rows]}
