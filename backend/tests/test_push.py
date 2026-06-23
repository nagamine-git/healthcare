from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

JST = ZoneInfo("Asia/Tokyo")


@pytest.fixture
def app_client(temp_data_dir, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(temp_data_dir))
    monkeypatch.setenv("HAE_INGEST_TOKEN", "test")
    monkeypatch.setenv("VAPID_PUBLIC_KEY", "BTestPublicKey")
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "dGVzdHByaXZhdGU")
    from app import main as main_module
    from app.config import Settings, reset_settings_cache

    reset_settings_cache()
    settings = Settings(scheduler_enabled=False, app_data_dir=temp_data_dir)
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    app = main_module.create_app()
    with TestClient(app) as client:
        yield client


SUB = {
    "endpoint": "https://push.example.com/abc123",
    "keys": {"p256dh": "p256dh-key", "auth": "auth-key"},
}


def test_config_reports_enabled_with_public_key(app_client):
    r = app_client.get("/api/push/config").json()
    assert r["enabled"] is True
    assert r["vapid_public_key"] == "BTestPublicKey"


def test_subscribe_and_unsubscribe(app_client):
    assert app_client.post("/api/push/subscribe", json=SUB).json()["status"] == "ok"
    # 同じ endpoint の再購読は UPSERT (重複しない)
    app_client.post("/api/push/subscribe", json=SUB)

    from app.db import session_scope
    from app.models import PushSubscription

    with session_scope() as s:
        rows = s.query(PushSubscription).all()
        assert len(rows) == 1
        assert rows[0].auth == "auth-key"

    r = app_client.post("/api/push/unsubscribe", json={"endpoint": SUB["endpoint"]}).json()
    assert r["removed"] is True


def test_test_endpoint_sends(app_client, monkeypatch):
    app_client.post("/api/push/subscribe", json=SUB)
    calls = []
    monkeypatch.setattr(
        "app.api.push.send_web_push", lambda sub, payload: calls.append(payload) or "ok"
    )
    r = app_client.post("/api/push/test", json=None).json()
    assert r["sent"] == 1
    assert calls[0]["tag"] == "hc-test"


# --- tick の送信・冪等性 ---


def _critical_alert():
    return {
        "code": "chronic_sleep_deficit",
        "severity": "critical",
        "title": "慢性睡眠不足",
        "detail": "直近3日で2日が5時間未満",
        "action": "14:30 に 20 分ナップ",
    }


@pytest.fixture
def db(temp_data_dir, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(temp_data_dir))
    monkeypatch.setenv("VAPID_PUBLIC_KEY", "BTestPublicKey")
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "dGVzdHByaXZhdGU")
    from app.config import reset_settings_cache

    reset_settings_cache()
    from app.db import create_all, init_engine

    init_engine(temp_data_dir / "test.sqlite3")
    create_all()
    yield


def test_tick_sends_then_dedupes(db, monkeypatch):
    from app.db import session_scope
    from app.models import NotificationLog, PushSubscription
    from app.notifications import service

    with session_scope() as s:
        s.add(
            PushSubscription(
                endpoint=SUB["endpoint"],
                p256dh="p",
                auth="a",
                ua=None,
                created_at=datetime(2026, 6, 21, 8),
            )
        )

    # データ収集は固定値を注入 (engine は別テストで網羅済み)
    monkeypatch.setattr(service, "_gather", lambda session, target: ([_critical_alert()], [], None))
    sent_payloads: list[dict] = []
    monkeypatch.setattr(
        service, "send_web_push", lambda sub, payload: sent_payloads.append(payload) or "ok"
    )

    now = datetime(2026, 6, 21, 9, 0, tzinfo=JST)
    r1 = service.run_notification_tick(now=now)
    assert r1["sent"] == 1
    assert sent_payloads[0]["priority"] == "critical"

    # 2 回目は NotificationLog により重複排除されて送らない
    r2 = service.run_notification_tick(now=now)
    assert r2["sent"] == 0

    with session_scope() as s:
        assert s.query(NotificationLog).count() == 1


def test_tick_removes_gone_subscription(db, monkeypatch):
    from app.db import session_scope
    from app.models import PushSubscription
    from app.notifications import service

    with session_scope() as s:
        s.add(
            PushSubscription(
                endpoint=SUB["endpoint"],
                p256dh="p",
                auth="a",
                ua=None,
                created_at=datetime(2026, 6, 21, 8),
            )
        )

    monkeypatch.setattr(service, "_gather", lambda session, target: ([_critical_alert()], [], None))
    monkeypatch.setattr(service, "send_web_push", lambda sub, payload: "gone")

    now = datetime(2026, 6, 21, 9, 0, tzinfo=JST)
    service.run_notification_tick(now=now)

    with session_scope() as s:
        assert s.query(PushSubscription).count() == 0


def test_tick_skips_when_no_subscriptions(db, monkeypatch):
    from app.notifications import service

    r = service.run_notification_tick(now=datetime(2026, 6, 21, 9, tzinfo=JST))
    assert r["skipped"] == "no_subscriptions"
