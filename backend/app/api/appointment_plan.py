"""「何時にどこに居たいか」から逆算して、その日の起床時刻を決める API。

⚠️ ここは**逆算チェーンの前段だけ**を担い、求めた起床時刻を既存の
``SleepPlanOverride`` に書く。就寝・入浴・夕食・カフェイン・PC仕事の締切は
``compute_tonight_plan`` が起床時刻から逆算するので、自動で全部追随する。
同じ逆算をここで再実装しないこと (2箇所に増えると必ず食い違う)。
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import get_settings
from app.db import session_scope
from app.models import SleepPlanOverride
from app.scoring.appointment_plan import plan_from_appointment
from app.scoring.sleep_plan import compute_tonight_plan
from app.scoring.timewindow import app_today

router = APIRouter()

_HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


class AppointmentIn(BaseModel):
    date: date_type | None = None          # 到着する日 (既定は明日)
    arrive_at: str = Field(pattern=_HHMM)  # 到着したい時刻
    travel_min: int = Field(ge=0, le=720)  # 移動にかかる分
    prep_min: int | None = None            # 身支度 (既定は config)
    place: str | None = Field(default=None, max_length=120)
    apply: bool = True                     # false なら保存せず試算だけ


@router.post("/api/sleep-plan/from-appointment")
def from_appointment(body: AppointmentIn) -> dict[str, Any]:
    """到着時刻から起床時刻を逆算し、その日の上書きとして適用する。"""
    s = get_settings()
    tz = ZoneInfo(s.app_tz)
    # 既定は「明日の予定」。今日の朝の予定を今から逆算しても手遅れなことが多い。
    target = body.date or (app_today() + __import__("datetime").timedelta(days=1))
    prep = body.prep_min if body.prep_min is not None else s.prep_to_departure_min

    try:
        back = plan_from_appointment(
            target, body.arrive_at, travel_min=body.travel_min, prep_min=prep, tz=tz
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    if body.apply:
        with session_scope() as ses:
            row = ses.execute(
                select(SleepPlanOverride).where(SleepPlanOverride.date == target)
            ).scalar_one_or_none()
            if row is None:
                row = SleepPlanOverride(date=target)
                ses.add(row)
            row.wake_time = back["wake_time"]
            row.updated_at = datetime.now(tz).replace(tzinfo=None)

    # 適用後の計画を返す。compressed / estimated_sleep_min から
    # 「この予定だと睡眠が削られる」ことが呼び出し側で判断できる。
    plan = compute_tonight_plan(app_today())
    return {
        **back,
        "place": body.place,
        "applied": body.apply,
        "plan": plan,
        # この予定を満たすと睡眠がどうなるか (UI の警告用)
        "sleep_compressed": bool(plan.get("compressed")),
        "estimated_sleep_min": plan.get("estimated_sleep_min"),
        "target_sleep_min": plan.get("target_sleep_min"),
    }
