"""通知 tick: 素材収集 → 候補選定 (engine) → 重複排除 → Web Push 送信 → 記録。

スケジューラ (5 分ごと) と手動テストから呼ばれる統合エントリ。
ここだけが DB と pywebpush の両方に触れる。選定ロジック自体は engine が純粋に持つ。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.config import get_settings
from app.db import session_scope
from app.logging import get_logger
from app.models import LlmComment, NotificationLog
from app.notifications.engine import DueNotification, collect_due_notifications
from app.notifications.push import (
    is_configured,
    list_subscriptions,
    send_web_push,
    subscription_to_dict,
)

logger = get_logger(__name__)


def _gather(session, target) -> tuple[list[dict], list[dict], dict | None]:
    """alerts / advice actions / tonight_plan を集める。"""
    from app.scoring.profile import resolve_profile
    from app.scoring.sleep_plan import compute_tonight_plan
    from app.scoring.wellbeing_alerts import evaluate_alerts
    from app.scoring.wellbeing_alerts import to_dict as alert_to_dict

    prof = resolve_profile()
    bmi_floor = round(18.5 * (prof.height_cm / 100) ** 2, 1)
    alerts = [
        alert_to_dict(a)
        for a in evaluate_alerts(
            session, target, target_weight_kg=prof.target_weight_kg, weight_lower_kg=bmi_floor
        )
    ]

    comment = session.execute(
        select(LlmComment)
        .where(LlmComment.date == target)
        .order_by(LlmComment.generated_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    actions: list[dict] = []
    if comment and isinstance(comment.payload, dict):
        actions = comment.payload.get("actions") or []

    try:
        tonight = compute_tonight_plan(target)
    except Exception as e:
        logger.warning("tonight_plan_failed_in_notify", error=str(e))
        tonight = None

    return alerts, actions, tonight


def _send_one(session, subs, n: DueNotification, now_naive: datetime) -> bool:
    """1 通知を全購読へ送る。1 件でも成功すれば True。失効購読は削除。"""
    payload = {
        "title": n.title,
        "body": n.body,
        "tag": n.tag,
        "url": n.url,
        "priority": n.priority,
    }
    any_ok = False
    for sub in list(subs):
        res = send_web_push(subscription_to_dict(sub), payload)
        if res == "ok":
            any_ok = True
            sub.last_success_at = now_naive
        elif res == "gone":
            session.delete(sub)
            subs.remove(sub)
    return any_ok


def run_notification_tick(now: datetime | None = None) -> dict[str, Any]:
    """1 回分の判定と送信。スケジューラから 5 分ごとに呼ばれる。

    Args:
        now: テスト用に現在時刻を注入できる (省略時は JST の現在時刻)。
    """
    s = get_settings()
    if not is_configured():
        return {"sent": 0, "skipped": "not_configured"}

    from app.scoring.timewindow import app_today

    tz = ZoneInfo(s.app_tz)
    if now is None:
        now = datetime.now(tz)
    now_naive = now.replace(tzinfo=None)

    with session_scope() as session:
        subs = list_subscriptions(session)
        if not subs:
            return {"sent": 0, "skipped": "no_subscriptions"}

        alerts, actions, tonight = _gather(session, app_today())
        due = collect_due_notifications(
            now=now,
            alerts=alerts,
            advice_actions=actions,
            tonight_plan=tonight,
            bedtime_reminder=s.push_bedtime_reminder,
            critical_alert_after_hour=s.push_critical_after_hour,
        )

        sent = 0
        for n in due:
            if session.get(NotificationLog, n.dedup_key) is not None:
                continue  # 同一日に送信済み
            if _send_one(session, subs, n, now_naive):
                session.add(
                    NotificationLog(
                        dedup_key=n.dedup_key, sent_at=now_naive, title=(n.title or "")[:255]
                    )
                )
                sent += 1

        logger.info("notification_tick", due=len(due), sent=sent, subs=len(subs))
        return {"sent": sent, "due": len(due), "subscriptions": len(subs)}


async def notification_tick_job() -> dict[str, Any]:
    """APScheduler 用 async ラッパ。ブロッキング I/O はスレッドに逃がす。"""
    import asyncio

    return await asyncio.to_thread(run_notification_tick)
