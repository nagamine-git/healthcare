from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.scoring.timewindow import app_today


@pytest.fixture
def app_client(temp_data_dir, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(temp_data_dir))
    monkeypatch.setenv("HAE_INGEST_TOKEN", "test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")

    from app import main as main_module
    from app.config import Settings, reset_settings_cache

    reset_settings_cache()
    settings = Settings(scheduler_enabled=False, app_data_dir=temp_data_dir)
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)

    app = main_module.create_app()
    with TestClient(app) as client:
        yield client


def test_ingest_learning_and_life(app_client):
    today = app_today().isoformat()
    resp = app_client.post(
        "/api/domain/learning/ingest",
        json={"date": today, "achievement": 65.0, "detail": "9軸平均偏差値58"},
    )
    assert resp.status_code == 200
    life = app_client.get("/api/life").json()
    learning = next(d for d in life["domains"] if d["key"] == "learning")
    assert learning["achievement"] == 65.0
    assert learning["detail"] == "9軸平均偏差値58"


def test_ingest_work_and_list(app_client):
    today = app_today().isoformat()
    app_client.post(
        "/api/domain/work/ingest",
        json={"date": today, "achievement": 80.0, "detail": "step100/git100/council40"},
    )
    body = app_client.get("/api/domain/work").json()
    assert body["data"][0]["achievement"] == 80.0
    assert body["data"][0]["detail"] == "step100/git100/council40"


def test_unknown_external_domain_404(app_client):
    resp = app_client.post(
        "/api/domain/health/ingest",
        json={"date": app_today().isoformat(), "achievement": 50.0},
    )
    assert resp.status_code == 404
