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


def test_post_then_get_checkin(app_client):
    resp = app_client.post("/api/checkin", json={"mood": 4, "energy": 3, "stress": 2, "soreness": 1})
    assert resp.status_code == 200
    body = resp.json()
    assert body["today"]["mood"] == 4
    assert body["today"]["stress"] == 2

    got = app_client.get("/api/checkin").json()
    assert got["today"]["energy"] == 3
    assert len(got["items"]) == 1


def test_partial_update_keeps_other_fields(app_client):
    app_client.post("/api/checkin", json={"mood": 5, "energy": 4})
    # mood だけ更新 → energy は保持
    resp = app_client.post("/api/checkin", json={"mood": 3})
    body = resp.json()
    assert body["today"]["mood"] == 3
    assert body["today"]["energy"] == 4


def test_out_of_range_rejected(app_client):
    assert app_client.post("/api/checkin", json={"mood": 0}).status_code == 422
    assert app_client.post("/api/checkin", json={"stress": 6}).status_code == 422


def test_get_empty_when_no_data(app_client):
    got = app_client.get("/api/checkin").json()
    assert got["today"] is None
    assert got["items"] == []


def test_clear_field(app_client):
    app_client.post("/api/checkin", json={"mood": 5, "energy": 4})
    resp = app_client.post("/api/checkin", json={"clear": ["mood"]})
    today = resp.json()["today"]
    assert today["mood"] is None
    assert today["energy"] == 4


def test_suggested_from_prior_days(app_client):
    from datetime import datetime, timedelta

    from app.db import session_scope
    from app.models import SubjectiveCheckin

    _dt = datetime
    today = app_today()
    with session_scope() as s:
        for i in (1, 2, 3):
            s.add(SubjectiveCheckin(date=today - timedelta(days=i), mood=4, energy=2,
                                    updated_at=_dt.now()))
    got = app_client.get("/api/checkin").json()
    assert got["suggested"]["mood"] == 4
    assert got["suggested"]["energy"] == 2
    assert got["suggested"]["stress"] is None


def test_suggested_from_objective_signals(app_client):
    """BB/睡眠/ストレス/トレ負荷から推定 (ORM detached を踏まない回帰)。"""

    from app.db import session_scope
    from app.models import BodyBattery, SleepSession
    from app.scoring.timewindow import jst_day_bounds

    today = app_today()
    start, _ = jst_day_bounds(today)
    with session_scope() as s:
        s.add(BodyBattery(ts=start.replace(tzinfo=None) if start.tzinfo else start, value=85.0))
        s.add(SleepSession(date=today, source="garmin", total_min=450, sleep_score=82))

    got = app_client.get("/api/checkin").json()
    # 活力 <- BB 85 -> 5
    assert got["suggested"]["energy"] == 5
