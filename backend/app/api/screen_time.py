"""スマホ使用時間 (スクリーンタイム) の取り込み API。

iOS は Screen Time の数値を API で公開していないため、毎晩
ショートカット (オートメーション) が数値を尋ねて POST する半自動方式。
日次 1 値を MetricSample (screen_time_min) として upsert する。
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db import session_scope
from app.models import MetricSample
from app.scoring.timewindow import app_today, jst_day_bounds

router = APIRouter()

_KEY = "screen_time_min"


class ScreenTimeIn(BaseModel):
    minutes: float = Field(gt=0, le=24 * 60)
    date: str | None = None  # ISO。省略時は今日 (JST)


@router.post("/api/screen-time")
async def post_screen_time(body: ScreenTimeIn) -> dict[str, Any]:
    from datetime import date as date_type

    target = date_type.fromisoformat(body.date) if body.date else app_today()
    start, _ = jst_day_bounds(target)
    ts = start + timedelta(hours=12)  # JST 正午相当に日次 1 サンプル
    with session_scope() as session:
        row = session.execute(
            select(MetricSample).where(
                MetricSample.source == "manual",
                MetricSample.metric_key == _KEY,
                MetricSample.ts == ts,
            )
        ).scalar_one_or_none()
        if row:
            row.value = body.minutes
        else:
            session.add(
                MetricSample(
                    source="manual", metric_key=_KEY, ts=ts,
                    value=body.minutes, unit="分",
                )
            )
    return {"date": target.isoformat(), "minutes": body.minutes}
