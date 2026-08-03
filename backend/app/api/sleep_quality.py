"""「昨夜の睡眠」評価 API。

薄いだけ: DB から今日 (=起床日) の ``SleepSession`` と、個人の目標睡眠時間
(``scoring/profile.py:resolve_profile()``) を引き、n-of-1 の実証要因
(``scoring/sleep_drivers.py:analyze()``) と合わせて ``scoring/sleep_quality.py:evaluate_last_night``
に渡すだけ。判定ロジックは一切ここに書かない。
"""

from __future__ import annotations

from datetime import UTC, timedelta
from datetime import date as date_type
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


def _history(target: date_type, days: int) -> list[dict[str, Any]]:
    """直近 ``days`` 夜の各指標を、``components`` と**同じ key** で返す。

    フロントは行ごとにこの系列をスパークラインとして描き、目安バンドと重ねて
    「今の値が band に入っているか」だけでなく「どちらへ動いているか」を見せる。

    ⚠️ 新しいエンドポイントを足さず既存レスポンスに同梱する。この画面はリクエスト数が
    そのまま体感の遅さになる (過去にリクエストが詰まって全画面が固まった経緯がある)。
    """
    from sqlalchemy import select

    with session_scope() as session:
        rows = session.execute(
            select(
                SleepSession.date, SleepSession.total_min, SleepSession.deep_min,
                SleepSession.rem_min, SleepSession.awake_min, SleepSession.sleep_score,
            )
            .where(SleepSession.date > target - timedelta(days=days),
                   SleepSession.date <= target)
            .order_by(SleepSession.date)
        ).all()

    by_date: dict[date_type, dict[str, Any]] = {}
    for d, total, deep, rem, awake, score in rows:
        if not total:
            continue  # 計測できていない夜は「0」ではなく**欠測**として扱う
        # 割合の分母は components と揃える (深睡眠/REM は総睡眠時間に対する割合)
        eff = (total / (total + awake) * 100) if awake is not None and (total + awake) > 0 else None
        by_date[d] = {
            "sleep_score": score,
            "deep": round(deep / total * 100, 1) if deep is not None else None,
            "rem": round(rem / total * 100, 1) if rem is not None else None,
            "efficiency": round(eff, 1) if eff is not None else None,
            "awake": awake,      # 分 (割合ではなく実分数で見る指標)
            "total": total,      # 分
        }

    # ⚠️ 計測できた夜だけを詰めて返してはいけない。1週間空いた夜が隣同士に描かれ、
    # 「毎晩測れているのに急変した」ように見えてしまう。**日付の位置を保ったまま**
    # 欠測を null で埋めて返し、描画側で点を落とす (線は繋ぐが位置は動かさない)。
    empty = {k: None for k in ("sleep_score", "deep", "rem", "efficiency", "awake", "total")}
    return [
        {"date": (d := target - timedelta(days=i)).isoformat(), **by_date.get(d, empty)}
        for i in range(days - 1, -1, -1)
    ]


@router.get("/api/sleep/last-night")
def get_last_night() -> dict[str, Any]:
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
        # 直近30夜のトレンド (components と同じ key)。行ごとのスパークライン用
        "history": _history(target, days=30),
        **result,
    }
