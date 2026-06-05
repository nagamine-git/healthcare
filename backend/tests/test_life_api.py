from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.models import MetricSample, SleepSession


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


def test_get_life(app_client):
    from app.db import session_scope
    from app.scoring.timewindow import jst_day_bounds

    today = date.today()
    start, _ = jst_day_bounds(today)
    with session_scope() as s:
        s.add(MetricSample(source="hae", metric_key="mindful_minutes", ts=start, value=15.0))
        s.add(SleepSession(date=today, source="garmin", total_min=480, sleep_score=80))

    resp = app_client.get("/api/life")
    assert resp.status_code == 200
    body = resp.json()
    assert "life_score" in body
    assert {d["key"] for d in body["domains"]} == {"health", "meditation", "speech"}
    assert any(p["key"] == "balanced" for p in body["presets"])


def test_put_weights(app_client):
    resp = app_client.put("/api/life/weights", json={"weights": {"health": 1.0, "meditation": 3.0}})
    assert resp.status_code == 200
    med = next(d for d in resp.json()["domains"] if d["key"] == "meditation")
    assert med["weight"] == 3.0


def test_apply_preset(app_client):
    resp = app_client.post("/api/life/preset/mindful")
    assert resp.status_code == 200
    med = next(d for d in resp.json()["domains"] if d["key"] == "meditation")
    assert med["weight"] == 2.0


def test_unknown_preset_404(app_client):
    resp = app_client.post("/api/life/preset/nonexistent")
    assert resp.status_code == 404
