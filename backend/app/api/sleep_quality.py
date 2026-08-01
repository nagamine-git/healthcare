"""「昨夜の睡眠」評価 API。

薄いだけ: DB から今日 (=起床日) の ``SleepSession`` と、個人の目標睡眠時間
(``scoring/profile.py:resolve_profile()``) を引き、n-of-1 の実証要因
(``scoring/sleep_drivers.py:analyze()``) と合わせて ``scoring/sleep_quality.py:evaluate_last_night``
に渡すだけ。判定ロジックは一切ここに書かない。
"""

from __future__ import annotations

from datetime import UTC
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter

from app.db import session_scope
from app.models import SleepSession
from app.scoring import sleep_drivers
from app.scoring.profile import resolve_profile
from app.scoring.sleep_quality import evaluate_last_night
from app.scoring.timewindow import app_today
from app.scoring.wake_detect import wake_stages_from_raw

router = APIRouter()

_JST = ZoneInfo("Asia/Tokyo")


def _wake_stages_payload(raw_json: dict[str, Any] | None) -> dict[str, Any] | None:
    """「目覚め (睡眠終了)」「起床 (体動確認)」を JST HH:MM で返す。

    体動から起床を検出できない夜は ``actual_wake_hhmm``/``lingering_min`` が
    None になる (呼び出し側=フロントで睡眠終了のみの1行表示にフォールバックする)。
    睡眠終了時刻自体が不明 (raw_json 無し等) なら None を返す。
    """
    stages = wake_stages_from_raw(raw_json)
    if stages is None:
        return None
    sleep_end_jst = stages["sleep_end_utc"].replace(tzinfo=UTC).astimezone(_JST)
    actual_wake_utc = stages["actual_wake_utc"]
    actual_wake_jst = (
        actual_wake_utc.replace(tzinfo=UTC).astimezone(_JST) if actual_wake_utc is not None else None
    )
    return {
        "sleep_end_hhmm": sleep_end_jst.strftime("%H:%M"),
        "actual_wake_hhmm": actual_wake_jst.strftime("%H:%M") if actual_wake_jst else None,
        "lingering_min": stages["lingering_min"],
    }


@router.get("/api/sleep/last-night")
async def get_last_night() -> dict[str, Any]:
    """昨夜 (SleepSession.date = 起床日 = 今日) の評価。データが無ければ available:false。"""
    target = app_today()
    # ⚠️ ORM オブジェクトを with の外へ持ち出さない。session_scope を抜けると
    # detach され、未ロード属性に触った瞬間 DetachedInstanceError で 500 になる。
    # 必要な値は**セッション内で素の値として取り出す**こと。
    with session_scope() as session:
        sleep = session.get(SleepSession, target)
        vals = None if sleep is None else {
            "total_min": sleep.total_min,
            "deep_min": sleep.deep_min,
            "rem_min": sleep.rem_min,
            "light_min": sleep.light_min,
            "awake_min": sleep.awake_min,
            "sleep_score": sleep.sleep_score,
        }
        # raw_json は素の dict なので detach 後に触っても問題ないが、念のため
        # セッション内で取り出しておく (上の vals と同じ作法)。
        wake_stages = _wake_stages_payload(sleep.raw_json) if sleep is not None else None

    if vals is None or vals["total_min"] is None:
        return {"date": target.isoformat(), "available": False}

    profile = resolve_profile()
    # sleep_drivers.analyze() は本人の n-of-1 統計分析。改善点の personal 根拠に使う
    # (strong/suggestive のみ実証済みとみなす、モジュール側の作法どおり)。
    driver = sleep_drivers.analyze(target)

    result = evaluate_last_night(
        **vals,
        sleep_need_min=profile.sleep_need_min,
        driver_quality=driver.get("quality"),
        driver_recommendations=driver.get("recommendations"),
    )
    if result is None:
        return {"date": target.isoformat(), "available": False}

    return {
        "date": target.isoformat(),
        "available": True,
        "wake_stages": wake_stages,
        **result,
    }
