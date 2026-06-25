from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_client(temp_data_dir, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(temp_data_dir))

    from app import main as main_module
    from app.config import Settings, reset_settings_cache

    reset_settings_cache()
    settings = Settings(scheduler_enabled=False, app_data_dir=temp_data_dir, anthropic_api_key=None)
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)

    app = main_module.create_app()
    with TestClient(app) as client:
        yield client


def test_becoming_get_shape(app_client):
    r = app_client.get("/api/becoming")
    assert r.status_code == 200
    body = r.json()
    assert {"date", "loop_week", "trajectory", "history"} <= set(body)


def test_becoming_backfill_then_history(app_client):
    r = app_client.post("/api/becoming/backfill")
    assert r.status_code == 200
    assert r.json()["filled"] > 0
    history = app_client.get("/api/becoming").json()["history"]
    assert len(history) > 0


def test_one_move_fallback_without_api_key(app_client):
    # anthropic_api_key=None なので構造化フォールバックが返る
    r = app_client.post("/api/becoming/one-move")
    assert r.status_code == 200
    body = r.json()
    assert {"move", "if_then", "dimension_id", "rationale"} <= set(body)
    assert body.get("fallback") is True
