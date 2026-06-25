from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_client(temp_data_dir, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(temp_data_dir))

    from app import main as main_module
    from app.config import Settings, reset_settings_cache

    reset_settings_cache()
    settings = Settings(scheduler_enabled=False, app_data_dir=temp_data_dir)
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)

    app = main_module.create_app()
    with TestClient(app) as client:
        yield client


def test_garden_get_returns_shape(app_client):
    r = app_client.get("/api/garden")
    assert r.status_code == 200
    body = r.json()
    assert {"date", "grid", "streak", "today", "catalog", "weakest_hint", "github"} <= set(body)
    assert isinstance(body["grid"], list)
    assert body["github"]["connected"] is False


def test_garden_log_then_today_has_action(app_client):
    r = app_client.post("/api/garden/log", json={"kind": "meditation"})
    assert r.status_code == 200
    assert "meditation" in r.json()["today"]["contributions"]


def test_garden_config_saves_username(app_client):
    r = app_client.post(
        "/api/garden/config", json={"github_username": "octocat", "github_token": "tok"}
    )
    assert r.status_code == 200
    assert r.json() == {"connected": True, "username": "octocat"}
    assert "github_token" not in r.json()
