"""Compass の定期ジョブ (APScheduler から呼ばれる)。

weekly: 意思決定ログを集計して現在地 (EWMA 合成) を更新する。
monthly: SJT 本測のリマインドを Web Push で送る (盲点は時間とともにずれるため再測定を促す)。
"""

from __future__ import annotations

from app.db import session_scope
from app.logging import get_logger

logger = get_logger(__name__)


async def identity_weekly_job() -> dict:
    """週次: 意思決定ログから現在地を再計算する。"""
    with session_scope() as session:
        from app.scoring.identity.store import recompute_dimension_scores

        currents = recompute_dimension_scores(session)
    logger.info("identity_weekly_recompute", n_dimensions=len(currents))
    return {"status": "ok", "dimensions": len(currents)}


async def identity_monthly_job() -> dict:
    """月次: SJT 本測のリマインドを送る。"""
    from app.config import get_settings

    settings = get_settings()
    from app.notifications.push import (
        is_configured,
        list_subscriptions,
        send_web_push,
        subscription_to_dict,
    )

    if not settings.push_enabled or not is_configured():
        logger.info("identity_monthly_reminder_skipped", reason="push_unconfigured")
        return {"status": "skipped"}

    payload = {
        "title": "Compass 月次チェック",
        "body": "今月の状況判断テスト (SJT) で現在地を測り直しましょう。",
        "url": "/#identity",
    }
    sent = 0
    with session_scope() as session:
        subs = [subscription_to_dict(s) for s in list_subscriptions(session)]
    for sub in subs:
        try:
            send_web_push(sub, payload)
            sent += 1
        except Exception as exc:  # 1 端末の失敗で全体を止めない
            logger.warning("identity_monthly_reminder_failed", error=str(exc))
    logger.info("identity_monthly_reminder_sent", sent=sent)
    return {"status": "ok", "sent": sent}
