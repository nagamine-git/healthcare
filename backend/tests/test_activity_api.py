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


def test_activity_signal_shape(app_client):
    r = app_client.get("/api/activity/signal?days=7")
    assert r.status_code == 200
    data = r.json()
    assert len(data["days"]) == 7
    for d in data["days"]:
        assert {"date", "moved", "went_outside", "confidence", "sources"} <= set(d)
    # データ皆無の temp DB では全日 unknown (None) であって False ではない
    assert all(d["moved"] is None for d in data["days"])
    assert all(d["confidence"] == "none" for d in data["days"])
