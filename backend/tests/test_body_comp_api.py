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


def test_extract_returns_draft(app_client, monkeypatch):
    import app.api.body_comp as bapi

    async def fake(**kwargs):
        return {
            "skeletal_muscle_kg": 18.4, "skeletal_muscle_pct": 34.2,
            "visceral_fat_level": 3.5, "bmr_kcal": 1363, "date": None,
        }

    monkeypatch.setattr(bapi, "extract_body_comp", fake)
    r = app_client.post("/api/body-composition/extract", json={"image_base64": "x"})
    assert r.status_code == 200
    assert r.json()["draft"]["skeletal_muscle_kg"] == 18.4


def test_put_upserts_by_date_and_lists(app_client):
    r = app_client.put(
        "/api/body-composition",
        json={"date": "2026-06-17", "skeletal_muscle_kg": 18.4, "visceral_fat_level": 3.5,
              "bmr_kcal": 1363},
    )
    assert r.status_code == 200
    assert r.json()["latest"]["skeletal_muscle_kg"] == 18.4
    # 同一日付は upsert(重複させない)
    app_client.put("/api/body-composition", json={"date": "2026-06-17", "skeletal_muscle_kg": 18.9})
    payload = app_client.get("/api/body-composition").json()
    assert len(payload["history"]) == 1
    assert payload["latest"]["skeletal_muscle_kg"] == 18.9


def test_put_rejects_all_empty(app_client):
    r = app_client.put("/api/body-composition", json={"date": "2026-06-17"})
    assert r.status_code == 422
