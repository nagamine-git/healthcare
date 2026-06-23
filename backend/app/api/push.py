"""Web Push 購読の登録・解除・テスト送信 API。

フロント (PWA) は:
  1. GET  /api/push/config        … VAPID public key と有効フラグを取得
  2. POST /api/push/subscribe     … PushManager の購読を保存
  3. POST /api/push/test          … 自分宛にテスト通知を送る
  4. POST /api/push/unsubscribe   … 購読を削除
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Header
from pydantic import BaseModel

from app.config import get_settings
from app.db import session_scope
from app.models import PushSubscription
from app.notifications.push import (
    delete_subscription,
    is_configured,
    send_web_push,
    subscription_to_dict,
    upsert_subscription,
)

router = APIRouter(prefix="/api/push")


class SubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class SubscriptionIn(BaseModel):
    endpoint: str
    keys: SubscriptionKeys


class UnsubscribeIn(BaseModel):
    endpoint: str


class TestIn(BaseModel):
    endpoint: str | None = None


def _now() -> datetime:
    return datetime.now(ZoneInfo(get_settings().app_tz)).replace(tzinfo=None)


@router.get("/config")
async def push_config() -> dict[str, Any]:
    """フロントが購読開始に必要な情報を返す。"""
    s = get_settings()
    return {
        "enabled": is_configured(),
        "vapid_public_key": s.vapid_public_key if is_configured() else None,
    }


@router.post("/subscribe")
async def subscribe(
    body: SubscriptionIn,
    user_agent: str | None = Header(default=None),
) -> dict[str, Any]:
    with session_scope() as session:
        upsert_subscription(
            session,
            endpoint=body.endpoint,
            p256dh=body.keys.p256dh,
            auth=body.keys.auth,
            ua=(user_agent or "")[:255] or None,
            now=_now(),
        )
    return {"status": "ok"}


@router.post("/unsubscribe")
async def unsubscribe(body: UnsubscribeIn) -> dict[str, Any]:
    with session_scope() as session:
        removed = delete_subscription(session, body.endpoint)
    return {"status": "ok", "removed": removed}


@router.post("/test")
async def test_push(body: TestIn | None = None) -> dict[str, Any]:
    """登録済みの購読 (または指定 endpoint) にテスト通知を送る。"""
    if not is_configured():
        return {"status": "disabled"}
    payload = {
        "title": "🔔 通知テスト",
        "body": "通知は正しく届いています。",
        "tag": "hc-test",
        "url": "/",
        "priority": "normal",
    }
    sent = 0
    with session_scope() as session:
        if body and body.endpoint:
            sub = session.get(PushSubscription, body.endpoint)
            subs = [sub] if sub else []
        else:
            from app.notifications.push import list_subscriptions

            subs = list_subscriptions(session)
        for sub in list(subs):
            res = send_web_push(subscription_to_dict(sub), payload)
            if res == "ok":
                sent += 1
            elif res == "gone":
                session.delete(sub)
    return {"status": "ok", "sent": sent}
