from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.scoring.timewindow import app_today, jst_day_bounds


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


def test_timeline_aggregates_day_in_jst_hours(app_client):
    from app.db import session_scope
    from app.models import (
        BodyBattery,
        CaffeineIntake,
        MetricSample,
        SleepSession,
        Workout,
    )

    today = app_today()
    start, _ = jst_day_bounds(today)
    with session_scope() as s:
        # JST 09:00 の BB (start = JST 00:00 の UTC naive)
        s.add(BodyBattery(ts=start + timedelta(hours=9), value=70.0))
        s.add(MetricSample(source="garmin", metric_key="stress",
                           ts=start + timedelta(hours=10), value=42.0))
        s.add(MetricSample(source="garmin", metric_key="sleep_midpoint_hour",
                           ts=start + timedelta(hours=7), value=3.5))
        s.add(SleepSession(date=today, source="garmin", total_min=420))
        s.add(Workout(id="w1", source="garmin", start=start + timedelta(hours=20),
                      end=start + timedelta(hours=20, minutes=30), type="strength_training"))
        s.add(CaffeineIntake(ts=start + timedelta(hours=8, minutes=30), source="green_tea",
                             amount=1.0, unit="杯", mg=30.0))

    body = app_client.get("/api/timeline").json()
    assert body["date"] == today.isoformat()
    assert body["body_battery"][0]["h"] == 9.0
    assert body["stress"][0]["v"] == 42.0
    # 睡眠: 中点 3.5h ± 3.5h (420分) = 0.0-7.0
    assert body["sleep"] == {"start_h": 0.0, "end_h": 7.0}
    assert body["workouts"][0]["start_h"] == 20.0
    assert body["caffeine"][0]["mg"] == 30.0
    assert body["migraine"] == []


def test_timeline_empty_day(app_client):
    body = app_client.get("/api/timeline").json()
    assert body["body_battery"] == []
    assert body["sleep"] is None
    assert body["checkin"] is None
