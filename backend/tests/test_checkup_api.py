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


def test_checkup_post_stores_multiple_exams_by_date(app_client, monkeypatch):
    # 1枚に2検査日(今回・前回)が含まれるケースをモック
    async def fake_extract(**kwargs):
        return {
            "exams": [
                {"date": "2026-04-01", "values": [
                    {"key": "ldl_c", "value": 160, "unit": "mg/dL"},
                    {"key": "junk", "value": 1, "unit": "x"},
                ]},
                {"date": "2025-04-01", "values": [
                    {"key": "ldl_c", "value": 110, "unit": "mg/dL"},
                ]},
            ],
        }

    import app.api.checkup as capi

    monkeypatch.setattr(capi, "extract_checkup", fake_extract)
    r = app_client.post("/api/checkup", json={"text": "..."})
    assert r.status_code == 200
    body = r.json()
    assert body["stored"] == 2
    # 最新(2026-04-01)が表示、履歴に2件
    assert body["latest"]["date"] == "2026-04-01"
    assert {v["key"]: v["flag"] for v in body["latest"]["values"]} == {"ldl_c": "high"}
    assert len(body["history"]) == 2


def test_checkup_reupload_same_date_upserts(app_client, monkeypatch):
    async def fake_extract(**kwargs):
        return {"exams": [{"date": "2026-04-01", "values": [
            {"key": "ldl_c", "value": 160, "unit": "mg/dL"}]}]}

    import app.api.checkup as capi

    monkeypatch.setattr(capi, "extract_checkup", fake_extract)
    app_client.post("/api/checkup", json={"text": "a"})
    r = app_client.post("/api/checkup", json={"text": "b"})
    # 同一日付は upsert(重複しない)
    assert len(r.json()["history"]) == 1


def test_checkup_post_requires_input(app_client):
    r = app_client.post("/api/checkup", json={})
    assert r.status_code == 400
