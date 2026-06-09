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


def test_ingest_and_list(app_client):
    today = app_today().isoformat()
    resp = app_client.post(
        "/api/speech/ingest",
        json={
            "date": today, "session_count": 2, "duration_min": 12.5,
            "score_overall": 78.0, "score_pace": 80, "score_pitch": 75,
            "score_clarity": 82, "score_filler": 70,
        },
    )
    assert resp.status_code == 200
    body = app_client.get("/api/speech").json()
    assert len(body["data"]) == 1
    assert body["data"][0]["score_overall"] == 78.0


def test_ingest_upsert(app_client):
    today = app_today().isoformat()
    app_client.post("/api/speech/ingest", json={"date": today, "session_count": 1, "score_overall": 50.0})
    app_client.post("/api/speech/ingest", json={"date": today, "session_count": 3, "score_overall": 88.0})
    body = app_client.get("/api/speech").json()
    assert len(body["data"]) == 1  # upsert (同日は1行)
    assert body["data"][0]["score_overall"] == 88.0


def test_speech_domain_in_life(app_client):
    from app.db import session_scope
    from app.models import SpeechSession

    with session_scope() as s:
        s.add(SpeechSession(date=app_today(), session_count=1, score_overall=90.0))
    resp = app_client.get("/api/life")
    speech = next(d for d in resp.json()["domains"] if d["key"] == "speech")
    assert speech["achievement"] == 90.0
