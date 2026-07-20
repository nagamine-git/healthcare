from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_client(temp_data_dir, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(temp_data_dir))
    monkeypatch.setenv("HAE_INGEST_TOKEN", "test")
    from app import main as main_module
    from app.config import Settings, reset_settings_cache

    reset_settings_cache()
    settings = Settings(scheduler_enabled=False, app_data_dir=temp_data_dir)
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    app = main_module.create_app()
    with TestClient(app) as client:
        yield client


def test_corporate_finance_not_connected_when_no_token(app_client):
    with patch("app.integrations.freee_client.has_token", return_value=False):
        r = app_client.get("/api/corporate-finance")
    assert r.status_code == 200
    body = r.json()
    assert body["connected"] is False
    assert body["data"] is None


def test_corporate_finance_returns_diagnosis_after_sync(app_client):
    trial_bs = {
        "fiscal_year": 2026,
        "balances": [
            {"account_category_name": "資産", "total_line": True, "hierarchy_level": 1,
             "closing_balance": 6650174},
            {"account_category_name": "負債", "total_line": True, "hierarchy_level": 1,
             "closing_balance": 5502748},
            {"account_category_name": "純資産", "total_line": True, "hierarchy_level": 1,
             "closing_balance": 1147426},
            {"account_category_name": "当期純損益金額", "total_line": True, "hierarchy_level": 5,
             "closing_balance": -1694555},
        ],
    }
    with (
        patch("app.integrations.freee_client.has_token", return_value=True),
        patch("app.integrations.freee_client.get_company",
              return_value={"id": 2395998, "name": "株式会社EFG technologies"}),
        patch("app.integrations.freee_client.fetch_trial_bs", return_value=trial_bs),
    ):
        sync_r = app_client.post("/admin/freee/sync")
        assert sync_r.status_code == 200

        r = app_client.get("/api/corporate-finance")
    assert r.status_code == 200
    body = r.json()
    assert body["connected"] is True
    assert body["data"]["net_assets_jpy"] == 1147426
    assert any(d["key"] == "deficit" for d in body["data"]["diagnosis"])


def test_freee_status_reports_configured(app_client):
    with patch("app.integrations.freee_client.has_token", return_value=True):
        r = app_client.get("/admin/freee/status")
    assert r.status_code == 200
    assert r.json() == {"configured": True}


def test_freee_oauth_start_redirects_to_authorize_url_with_state(app_client):
    r = app_client.get("/admin/freee/oauth/start", follow_redirects=False)
    assert r.status_code in (302, 307)
    location = r.headers["location"]
    assert "accounts.secure.freee.co.jp" in location
    assert "state=" in location  # CSRF対策のstateが必ず付与される


def test_freee_oauth_callback_exchanges_code_and_syncs(app_client):
    start = app_client.get("/admin/freee/oauth/start", follow_redirects=False)
    state = start.headers["location"].split("state=")[1].split("&")[0]

    with (
        patch("app.integrations.freee_client.exchange_code") as mock_exchange,
        patch("app.ingest.freee_sync.sync_corporate_finance") as mock_sync,
    ):
        r = app_client.get(
            "/admin/freee/oauth/callback", params={"code": "abc", "state": state}, follow_redirects=False,
        )
    assert r.status_code in (302, 307)
    mock_exchange.assert_called_once_with("abc")
    mock_sync.assert_called_once()


def test_freee_oauth_callback_rejects_missing_state(app_client):
    with patch("app.integrations.freee_client.exchange_code") as mock_exchange:
        r = app_client.get(
            "/admin/freee/oauth/callback", params={"code": "abc", "state": "not-issued"},
            follow_redirects=False,
        )
    assert r.status_code == 400
    mock_exchange.assert_not_called()


def test_freee_oauth_callback_rejects_reused_state(app_client):
    start = app_client.get("/admin/freee/oauth/start", follow_redirects=False)
    state = start.headers["location"].split("state=")[1].split("&")[0]

    with (
        patch("app.integrations.freee_client.exchange_code"),
        patch("app.ingest.freee_sync.sync_corporate_finance"),
    ):
        first = app_client.get(
            "/admin/freee/oauth/callback", params={"code": "abc", "state": state}, follow_redirects=False,
        )
        second = app_client.get(
            "/admin/freee/oauth/callback", params={"code": "abc", "state": state}, follow_redirects=False,
        )
    assert first.status_code in (302, 307)
    assert second.status_code == 400  # 使い切り (リプレイ攻撃対策)
