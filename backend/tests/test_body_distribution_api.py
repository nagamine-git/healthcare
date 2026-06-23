from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_client(temp_data_dir, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(temp_data_dir))
    monkeypatch.setenv("HAE_INGEST_TOKEN", "test")
    from app import main as main_module
    from app.config import Settings, reset_settings_cache

    reset_settings_cache()
    settings = Settings(scheduler_enabled=False, app_data_dir=temp_data_dir)
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    app = main_module.create_app()
    with TestClient(app) as client:
        yield client


def test_distribution_shape(app_client):
    r = app_client.get("/api/physique/distribution")
    assert r.status_code == 200
    data = r.json()
    assert "evaluable" in data
    keys = {m["key"] for m in data["metrics"]}
    assert keys == {"bmi", "body_fat", "ffmi", "vo2max"}
    for m in data["metrics"]:
        assert {"value", "mean", "sd", "percentile", "source", "target", "label", "unit"} <= set(m)
