from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


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


def test_mental_status_due_when_empty(app_client):
    r = app_client.get("/api/mental")
    assert r.status_code == 200
    d = r.json()
    assert d["due"] is True                 # 未実施 → 促す
    assert d["latest"] is None
    assert len(d["items"]) == 4             # PHQ-2 + GAD-2
    assert len(d["scale"]) == 4             # 0-3


def test_mental_screen_records_and_scores(app_client):
    r = app_client.post("/api/mental/screen",
                        json={"phq2_1": 3, "phq2_2": 3, "gad2_1": 2, "gad2_2": 1})
    assert r.status_code == 200
    d = r.json()
    assert d["latest"]["phq2"] == 6
    assert d["latest"]["gad2"] == 3
    assert d["latest"]["phq4"] == 9
    assert d["latest"]["depression_positive"] is True
    assert d["latest"]["anxiety_positive"] is True
    assert d["latest"]["severity"] == "severe"
    assert d["days_since_last"] == 0
    assert d["due"] is False                # 実施直後は促さない


def test_mental_screen_rejects_out_of_range(app_client):
    r = app_client.post("/api/mental/screen",
                        json={"phq2_1": 5, "phq2_2": 0, "gad2_1": 0, "gad2_2": 0})
    assert r.status_code == 422             # pydantic ge/le で弾く


def test_severe_screen_surfaces_wellbeing_alert(app_client):
    app_client.post("/api/mental/screen",
                    json={"phq2_1": 3, "phq2_2": 3, "gad2_1": 3, "gad2_2": 3})  # phq4=12 重度
    today = app_client.get("/api/today").json()
    codes = [a["code"] for a in (today.get("alerts") or [])]
    assert "mental_distress" in codes
    alert = next(a for a in today["alerts"] if a["code"] == "mental_distress")
    assert alert["severity"] == "critical"
