"""ワークアウト一言評価 API — 一覧 (保存済み評価つき) と、タップ時のオンデマンド生成。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.db import session_scope
from app.models import Workout, WorkoutReview

router = APIRouter()

_TYPE_LABEL = {
    "running": "ランニング", "strength_training": "筋トレ", "weight_training": "筋トレ",
    "boxing": "ボクシング", "walking": "ウォーキング", "hiking": "ハイキング",
    "indoor_climbing": "クライミング", "cycling": "サイクリング",
}


def _item(w: Workout, r: WorkoutReview | None) -> dict[str, Any]:
    jst = w.start + timedelta(hours=9)
    return {
        "workout_id": w.id,
        "date": jst.date().isoformat(),
        "start_jst": jst.strftime("%H:%M"),
        "type": w.type,
        "type_label": _TYPE_LABEL.get(w.type or "", w.type or "運動"),
        "duration_min": round((w.duration_s or 0) / 60) if w.duration_s else None,
        "review_text": r.text if r else None,
        "review_tone": r.tone if r else None,
        "reviewed_at": (
            r.created_at.replace(tzinfo=UTC).isoformat() if r and r.created_at else None
        ),
    }


@router.get("/api/workout-reviews")
async def list_reviews(days: int = 2) -> dict[str, Any]:
    """直近のワークアウト一覧 (保存済みの一言評価つき、新しい順)。"""
    since = datetime.utcnow() - timedelta(days=days)
    with session_scope() as session:
        rows = session.execute(
            select(Workout).where(Workout.start >= since).order_by(Workout.start.desc())
        ).scalars().all()
        reviews = {
            r.workout_id: r
            for r in session.execute(
                select(WorkoutReview).where(WorkoutReview.workout_id.in_([w.id for w in rows]))
            ).scalars()
        } if rows else {}
        items = [_item(w, reviews.get(w.id)) for w in rows]
    return {"items": items}


@router.post("/api/workout-reviews/{workout_id}")
async def create_review(workout_id: str, force: bool = False) -> dict[str, Any]:
    """一言評価を生成して保存。保存済みならそれを返す (冪等・LLM はタップ時の1回だけ)。"""
    with session_scope() as session:
        w = session.get(Workout, workout_id)
        if w is None:
            raise HTTPException(status_code=404, detail="workout not found")
        existing = session.get(WorkoutReview, workout_id)
        if existing is not None and not force:
            return _item(w, existing)

    from app.llm.workout_review import generate_review

    got = await generate_review(workout_id)
    if got is None:
        raise HTTPException(status_code=503, detail="評価を生成できませんでした (LLM 未設定/失敗)")
    with session_scope() as session:
        w = session.get(Workout, workout_id)
        if w is None:
            raise HTTPException(status_code=404, detail="workout not found")
        row = session.get(WorkoutReview, workout_id)
        if row is None:
            row = WorkoutReview(workout_id=workout_id, text=got["text"])
            session.add(row)
        row.text = got["text"]
        row.tone = got["tone"]
        row.model = got.get("model")
        row.created_at = datetime.utcnow()
        session.flush()
        return _item(w, row)
