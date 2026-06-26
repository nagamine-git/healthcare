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


def test_checkup_get_empty(app_client):
    r = app_client.get("/api/checkup")
    assert r.status_code == 200
    assert r.json()["latest"] is None


def test_checkup_post_extracts_and_flags(app_client, monkeypatch):
    # LLM 抽出をモック(LDL 高値・HbA1c 正常)
    async def fake_extract(**kwargs):
        return {
            "date": "2026-04-01",
            "values": [
                {"key": "ldl_c", "value": 160, "unit": "mg/dL"},
                {"key": "hba1c", "value": 5.2, "unit": "%"},
                {"key": "junk", "value": 1, "unit": "x"},
            ],
        }

    import app.api.checkup as capi

    monkeypatch.setattr(capi, "extract_checkup", fake_extract)
    r = app_client.post("/api/checkup", json={"text": "LDL 160 HbA1c 5.2"})
    assert r.status_code == 200
    latest = r.json()["latest"]
    assert latest["date"] == "2026-04-01"
    flags = {v["key"]: v["flag"] for v in latest["values"]}
    assert flags == {"ldl_c": "high", "hba1c": "normal"}  # junk は除外
    assert "LDL" in latest["summary"]


def test_checkup_post_requires_input(app_client):
    r = app_client.post("/api/checkup", json={})
    assert r.status_code == 400
