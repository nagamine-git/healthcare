"""ワークアウト評価 API — 一覧 (保存済み評価つき) と、タップ時のオンデマンド生成/再分析。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from app.config import get_settings
from app.db import session_scope
from app.models import LlmRegenLog, Workout, WorkoutReview
from app.scoring.timewindow import app_today

router = APIRouter()

_TYPE_LABEL = {
    "running": "ランニング", "strength_training": "筋トレ", "weight_training": "筋トレ",
    "boxing": "ボクシング", "walking": "ウォーキング", "hiking": "ハイキング",
    "indoor_climbing": "クライミング", "cycling": "サイクリング",
}

# 「再分析」(既存評価の明示的な force 再生成) の日次上限に使う識別子。
# アドバイス再生成 (llm_max_regenerations_per_day) と同じ考え方を流用しつつ、
# 機能ごとに別枠で数える (LlmRegenLog.feature で分離)。
_REGEN_FEATURE = "workout_review"


def _est_vo2max(session, w: Workout) -> dict[str, Any] | None:
    """ラン系のみ、公表式で幅つき推定 (Garmin 欠測時のフォールバック参考値)。

    実装は scoring/vo2max_estimate.py に集約 (garmin_sync の永続化と共用)。
    """
    from app.scoring.vo2max_estimate import estimate_for_workout

    return estimate_for_workout(
        session,
        workout_type=w.type,
        start=w.start,
        duration_s=w.duration_s,
        avg_hr=w.avg_hr,
        max_hr=w.max_hr,
        distance_m=w.distance_m,
        raw_json=w.raw_json,
    )


def _item(w: Workout, r: WorkoutReview | None, est: dict[str, Any] | None = None) -> dict[str, Any]:
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
        # 種目ごとの構造化評価 (筋トレで exercise_sets が取れた場合のみ)。無ければ None
        # (ラン等の従来どおり総合コメントのみのワークアウト)。
        "review_exercises": r.exercises_json if r else None,
        "reviewed_at": (
            r.created_at.replace(tzinfo=UTC).isoformat() if r and r.created_at else None
        ),
        "est_vo2max": est,
    }


def _check_regen_rate_limit(session: Any) -> None:
    """「再分析」の日次上限 (llm_max_regenerations_per_day と同じ発想・別枠でカウント)。

    無制限連打を防ぐ最終防衛線。連打そのものはフロント側で pending 中ボタン disable
    により防ぐが、複数タブ/リロード後の再送などをサーバー側でも塞いでおく。
    超過時は 429 (フロントはボタンを無効化しつつエラーメッセージを出す)。
    """
    settings = get_settings()
    today = app_today()
    count = session.execute(
        select(func.count(LlmRegenLog.id)).where(
            LlmRegenLog.feature == _REGEN_FEATURE, LlmRegenLog.date == today
        )
    ).scalar()
    if count and count >= settings.llm_max_regenerations_per_day:
        raise HTTPException(
            status_code=429,
            detail=f"本日の再分析の上限 ({settings.llm_max_regenerations_per_day}回) に達しました。",
        )


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
        items = [_item(w, reviews.get(w.id), _est_vo2max(session, w)) for w in rows]
    return {"items": items}


@router.post("/api/workout-reviews/{workout_id}")
async def create_review(workout_id: str, force: bool = False) -> dict[str, Any]:
    """評価を生成して保存。保存済みならそれを返す (冪等)。

    force=true は「再分析」の明示的な上書き要求。初回生成 (existing が無い) はワークアウト数
    そのもので自然に頭打ちになるためレート制限の対象外、既存評価の上書きだけ日次上限をかける。
    """
    with session_scope() as session:
        w = session.get(Workout, workout_id)
        if w is None:
            raise HTTPException(status_code=404, detail="workout not found")
        existing = session.get(WorkoutReview, workout_id)
        if existing is not None and not force:
            return _item(w, existing, _est_vo2max(session, w))
        if existing is not None and force:
            _check_regen_rate_limit(session)

    from app.llm.workout_review import generate_review

    got = await generate_review(workout_id)
    if got is None:
        raise HTTPException(status_code=503, detail="評価を生成できませんでした (LLM 未設定/失敗)")
    with session_scope() as session:
        w = session.get(Workout, workout_id)
        if w is None:
            raise HTTPException(status_code=404, detail="workout not found")
        row = session.get(WorkoutReview, workout_id)
        is_regen = row is not None and force
        if row is None:
            row = WorkoutReview(workout_id=workout_id, text=got["text"])
            session.add(row)
        row.text = got["text"]
        row.tone = got["tone"]
        row.model = got.get("model")
        row.exercises_json = got.get("exercises")
        row.created_at = datetime.utcnow()
        if is_regen:
            session.add(LlmRegenLog(feature=_REGEN_FEATURE, date=app_today()))
        session.flush()
        return _item(w, row, _est_vo2max(session, w))
