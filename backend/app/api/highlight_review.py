"""ハイライトイベント評価 API — タップで生成し (date, event_key) で永続化。"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.config import get_settings
from app.db import session_scope
from app.models import HighlightReview, LlmRegenLog
from app.scoring.timewindow import app_today

router = APIRouter()

# 「再分析」(既存評価の force 再生成) の日次上限に使う識別子。
# workout_review と同じ仕組みだが、機能ごとに別枠で数える (LlmRegenLog.feature で分離)。
_REGEN_FEATURE = "highlight_review"


def _check_regen_quota(session) -> None:
    """再分析の日次上限。超過なら 429。

    force 再生成は必ず LLM を1回叩くので、UI から無制限に叩けると費用が青天井になる。
    アドバイス再生成 (llm_max_regenerations_per_day) と同じ上限値を流用する。
    """
    settings = get_settings()
    count = session.execute(
        select(func.count(LlmRegenLog.id)).where(
            LlmRegenLog.feature == _REGEN_FEATURE, LlmRegenLog.date == app_today()
        )
    ).scalar()
    if count and count >= settings.llm_max_regenerations_per_day:
        raise HTTPException(
            status_code=429,
            detail=f"本日の再分析の上限 ({settings.llm_max_regenerations_per_day}回) に達しました。",
        )


def _to_dict(r: HighlightReview) -> dict[str, Any]:
    return {
        "date": r.date.isoformat(),
        "event_key": r.event_key,
        "text": r.text,
        "tone": r.tone,
    }


@router.get("/api/highlight-reviews")
def list_reviews(days: int = 3) -> dict[str, Any]:
    """直近 N 日の保存済みイベント評価 (クライアントは date+event_key で突き合わせる)。"""
    since = app_today() - timedelta(days=days)
    with session_scope() as session:
        rows = session.execute(
            select(HighlightReview).where(HighlightReview.date >= since)
        ).scalars().all()
        items = [_to_dict(r) for r in rows]
    return {"items": items}


class HighlightReviewIn(BaseModel):
    date: str
    event_key: str = Field(max_length=160)  # "HH:MM|ラベル"
    label: str = Field(max_length=80)
    time_jst: str | None = None
    sub: str | None = Field(default=None, max_length=200)
    force: bool = False


@router.post("/api/highlight-reviews")
async def create_review(body: HighlightReviewIn) -> dict[str, Any]:
    """評価を生成して保存。保存済みならそれを返す (冪等・LLM はタップ時の1回だけ)。"""
    try:
        target = date_type.fromisoformat(body.date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid date: {body.date}") from exc

    with session_scope() as session:
        existing = session.execute(
            select(HighlightReview).where(
                HighlightReview.date == target, HighlightReview.event_key == body.event_key
            )
        ).scalars().first()
        if existing is not None and not body.force:
            return _to_dict(existing)
        # 再分析 (既存を作り直す force) は LLM を必ず1回叩くので日次上限をかける。
        # 初回生成は対象外 (それが無いと評価そのものが得られない)。
        # workout_review と同じ仕組みだが LlmRegenLog.feature で別枠に数える。
        if existing is not None:
            _check_regen_quota(session)

    from app.llm.highlight_review import generate_review

    got = await generate_review(
        target=target, label=body.label, time_jst=body.time_jst, sub=body.sub
    )
    if got is None:
        raise HTTPException(status_code=503, detail="評価を生成できませんでした (LLM 未設定/失敗)")
    with session_scope() as session:
        row = session.execute(
            select(HighlightReview).where(
                HighlightReview.date == target, HighlightReview.event_key == body.event_key
            )
        ).scalars().first()
        if row is None:
            row = HighlightReview(date=target, event_key=body.event_key, text=got["text"])
            session.add(row)
        else:
            # 既存を作り直した = 再分析。上限カウントを消費する (初回生成は数えない)。
            session.add(LlmRegenLog(feature=_REGEN_FEATURE, date=app_today()))
        row.text = got["text"]
        row.tone = got["tone"]
        row.model = got.get("model")
        row.created_at = datetime.utcnow()
        session.flush()
        return _to_dict(row)
