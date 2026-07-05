"""トレーニング状況を「これまで→今→これから」で1本化する。

散在していたトレ情報 (いまコレ/ハイライト/部位別/今夜の計画/トレンド) を集約:
- これまで: 今週 (直近7日) の筋トレ回数・有酸素回数、目標3回への達成、14日筋トレ日数
- 今:       部位別回復サマリ (bodyload) + 「今週足りてる?」判定
- これから: 今日やるべき部位 (bodyload.suggestion) + 週目標まで「あとN回」

純関数 `build_status(sessions, groups, now)` に集計を分離しテスト可能にする。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.db import session_scope
from app.llm.client import _STRENGTH_TYPES
from app.models import Workout

WEEK_STRENGTH_TARGET = 3  # 筋肥大フェーズの週あたり筋トレ目標
_CARDIO_TYPES = {"running", "treadmill_running", "trail_running", "cycling", "walking",
                 "boxing", "hiking", "indoor_cardio", "hiit"}


def _is_strength(ty: str | None) -> bool:
    return bool(ty in _STRENGTH_TYPES or (ty and "strength" in ty.lower()))


def build_status(
    sessions: list[dict[str, Any]], groups: list[dict[str, Any]], now: datetime
) -> dict[str, Any]:
    """sessions: [{date(JST), type}], groups: bodyload の groups。now は JST naive。"""
    week_start = (now - timedelta(days=7)).date()
    fortnight_start = (now - timedelta(days=14)).date()

    stren_days_week: set = set()
    cardio_days_week: set = set()
    stren_days_14: set = set()
    for s in sessions:
        d = s["date"]
        if _is_strength(s["type"]):
            if d >= fortnight_start:
                stren_days_14.add(d)
            if d >= week_start:
                stren_days_week.add(d)
        elif s["type"] in _CARDIO_TYPES and d >= week_start:
            cardio_days_week.add(d)

    week_strength = len(stren_days_week)
    remaining = max(0, WEEK_STRENGTH_TARGET - week_strength)
    if week_strength >= WEEK_STRENGTH_TARGET:
        verdict = "enough"
    elif week_strength <= 1:
        verdict = "way_behind"
    else:
        verdict = "behind"

    recovered = sum(1 for g in groups if g.get("recovery_pct", 0) >= 80)
    recovering = sum(1 for g in groups if 40 <= g.get("recovery_pct", 0) < 80)
    loaded = sum(1 for g in groups if g.get("recovery_pct", 100) < 40)

    return {
        "past": {
            "week_strength": week_strength,
            "week_cardio": len(cardio_days_week),
            "strength_14d": len(stren_days_14),
            "target_week": WEEK_STRENGTH_TARGET,
        },
        "now": {
            "verdict": verdict,          # enough | behind | way_behind
            "recovered": recovered,
            "recovering": recovering,
            "loaded": loaded,
        },
        "next": {
            "remaining_this_week": remaining,
            # 今日やるべき部位は bodyload.suggestion を呼び出し側で結合
        },
    }


def state(*, now: datetime | None = None) -> dict[str, Any]:
    from app.scoring import bodyload

    now = now or datetime.now().replace(tzinfo=None)
    bl = bodyload.state()
    with session_scope() as db:
        since = datetime.utcnow() - timedelta(days=15)
        rows = db.execute(
            select(Workout.start, Workout.type).where(Workout.start >= since)
        ).all()
    sessions = [{"date": (st + timedelta(hours=9)).date(), "type": ty} for st, ty in rows]
    status = build_status(sessions, bl.get("groups", []), now)
    status["next"]["today_should_train"] = bl.get("suggestion", [])
    status["confidence"] = bl.get("confidence", "none")
    return status
