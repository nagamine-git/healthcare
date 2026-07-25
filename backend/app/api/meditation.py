"""就寝前の「瞑想 (ボディスキャン/呼吸瞑想)」を出し分ける API。

判定ロジック本体は ``scoring/meditation.py`` (DB 非依存の純関数)。ここでは既存の
就寝逆算 (``scoring/sleep_plan.py``)・直近の主観ストレス (``models/health.py:SubjectiveCheckin``)
を集めて渡すだけ。``api/wind_down.py`` (呼吸法) と対になる薄い API — 役割分担は
``scoring/meditation.py`` の docstring を参照。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import session_scope
from app.models import SubjectiveCheckin
from app.scoring.meditation import recommend_meditation
from app.scoring.sleep_plan import compute_tonight_plan
from app.scoring.timewindow import app_today

router = APIRouter()


def _latest_stress(session: Session, target, max_age_days: int) -> int | None:
    """直近の主観ストレス値。無ければ None。

    **鮮度を必ず制限する**: ストレスは日単位で変わる状態量なので、遡り無制限にすると
    何週間も前の高ストレス値が「今夜の状態」として body_scan を選び続けてしまう
    (wind_down 側が baseline_window_days で遡りを制限しているのと同じ理由)。
    """
    oldest = target - timedelta(days=max_age_days)
    row = session.execute(
        select(SubjectiveCheckin)
        .where(
            SubjectiveCheckin.date <= target,
            SubjectiveCheckin.date >= oldest,
            SubjectiveCheckin.stress.is_not(None),
        )
        .order_by(SubjectiveCheckin.date.desc())
        .limit(1)
    ).scalar_one_or_none()
    return row.stress if row is not None else None


@router.get("/api/meditation")
async def get_meditation() -> dict[str, Any]:
    settings = get_settings()
    tz = ZoneInfo(settings.app_tz)
    now = datetime.now(tz)
    target = app_today()

    plan = compute_tonight_plan(target, now=now)
    target_bedtime = datetime.fromisoformat(plan["bedtime_iso"])

    with session_scope() as session:
        stress_level = _latest_stress(
            session, target, settings.meditation_stress_max_age_days
        )

    result = recommend_meditation(
        now=now,
        target_bedtime=target_bedtime,
        stress_level=stress_level,
        minutes_target=settings.meditation_target_min,
        stress_high_threshold=settings.meditation_stress_high_threshold,
        body_scan_min_min=settings.meditation_body_scan_min_min,
        body_scan_max_min=settings.meditation_body_scan_max_min,
        breath_awareness_min_min=settings.meditation_breath_awareness_min_min,
        breath_awareness_max_min=settings.meditation_breath_awareness_max_min,
        bell_interval_sec=settings.meditation_bell_interval_sec,
    )
    result["target_bedtime"] = plan["bedtime"]
    return result
