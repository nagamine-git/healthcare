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


def test_get_profile_default(app_client):
    resp = app_client.get("/api/profile")
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "default"
    assert body["target_weight_kg"] == 65.0  # 例プロファイル


def test_put_profile_persists_and_resolves(app_client):
    resp = app_client.put("/api/profile", json={
        "height_cm": 165.0, "sex": "male",
        "target_weight_kg": 55.0, "target_body_fat_pct": 15.0,
        "ffmi_normalized": 18.0,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "db"
    assert body["target_weight_kg"] == 55.0

    # GET でも反映
    got = app_client.get("/api/profile").json()
    assert got["target_weight_kg"] == 55.0
    assert got["height_cm"] == 165.0


def test_put_profile_rejects_severe_underweight(app_client):
    # 165cm で目標 40kg = BMI 14.7 → 422
    resp = app_client.put("/api/profile", json={
        "height_cm": 165.0, "sex": "male",
        "target_weight_kg": 40.0, "target_body_fat_pct": 10.0,
    })
    assert resp.status_code == 422


def test_put_profile_returns_warnings_for_low_bmi(app_client):
    # BMI 17 台 (低体重だが保存は可) → warning を含む
    resp = app_client.put("/api/profile", json={
        "height_cm": 165.0, "sex": "male",
        "target_weight_kg": 48.0, "target_body_fat_pct": 12.0,
    })
    assert resp.status_code == 200
    assert resp.json()["assessment"]["level"] == "warning"
