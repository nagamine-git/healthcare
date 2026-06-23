"""Web Push の配信と購読 (PushSubscription) の管理。

pywebpush は本番 (Docker) でのみ必要なので import は関数内に遅延させる
(ローカルのユニットテストでは未インストールでも engine 側が動く)。
VAPID private key は base64url の raw スカラで保持し、送信時に PEM を一時生成する
(env に PEM 改行を持たせないため + py_vapid のバージョン差を吸収するため)。
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.logging import get_logger
from app.models import PushSubscription

logger = get_logger(__name__)

_pem_path: str | None = None


def is_configured() -> bool:
    """VAPID 鍵が揃っていて通知が有効か。"""
    s = get_settings()
    return bool(s.push_enabled and s.vapid_public_key and s.vapid_private_key)


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def _private_key_pem_path() -> str:
    """raw base64url private スカラから PKCS8 PEM を生成し一時ファイルに置く (キャッシュ)。"""
    global _pem_path
    if _pem_path and os.path.exists(_pem_path):
        return _pem_path

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    s = get_settings()
    raw = _b64url_decode(s.vapid_private_key or "")
    private_int = int.from_bytes(raw, "big")
    key = ec.derive_private_key(private_int, ec.SECP256R1())
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    fd, path = tempfile.mkstemp(prefix="vapid_", suffix=".pem")
    with os.fdopen(fd, "wb") as f:
        f.write(pem)
    os.chmod(path, 0o600)
    _pem_path = path
    return path


# ----- 購読 (subscription) CRUD -----


def subscription_to_dict(sub: PushSubscription) -> dict[str, Any]:
    """pywebpush が要求する subscription_info 形式に変換。"""
    return {
        "endpoint": sub.endpoint,
        "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
    }


def list_subscriptions(session: Session) -> list[PushSubscription]:
    return list(session.execute(select(PushSubscription)).scalars().all())


def upsert_subscription(
    session: Session,
    *,
    endpoint: str,
    p256dh: str,
    auth: str,
    ua: str | None,
    now,
) -> PushSubscription:
    sub = session.get(PushSubscription, endpoint)
    if sub is None:
        sub = PushSubscription(endpoint=endpoint, p256dh=p256dh, auth=auth, ua=ua, created_at=now)
        session.add(sub)
    else:
        sub.p256dh = p256dh
        sub.auth = auth
        sub.ua = ua
    return sub


def delete_subscription(session: Session, endpoint: str) -> bool:
    sub = session.get(PushSubscription, endpoint)
    if sub is None:
        return False
    session.delete(sub)
    return True


# ----- 送信 -----


def send_web_push(subscription: dict[str, Any], payload: dict[str, Any]) -> str:
    """1 件の購読へ送信する。

    Returns:
        "ok"   送信成功
        "gone" 購読が失効 (404/410) — 呼び出し側で削除すべき
        "error" その他の失敗 (一時的の可能性)
    """
    from pywebpush import WebPushException, webpush

    s = get_settings()
    try:
        webpush(
            subscription_info=subscription,
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=_private_key_pem_path(),
            vapid_claims={"sub": s.vapid_subject},
            ttl=3600,
        )
        return "ok"
    except WebPushException as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        if status in (404, 410):
            return "gone"
        logger.warning("web_push_failed", status=status, error=str(e))
        return "error"
    except Exception as e:
        logger.warning("web_push_unexpected_error", error=str(e))
        return "error"
