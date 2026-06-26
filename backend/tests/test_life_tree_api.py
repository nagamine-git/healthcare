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


def test_life_tree_shape(app_client):
    r = app_client.get("/api/life/tree")
    assert r.status_code == 200
    body = r.json()
    assert {"purpose", "goal", "capitals", "life_score", "focus_capital", "breaches"} <= set(body)
    keys = {c["key"] for c in body["capitals"]}
    assert {"body", "mind", "intellect", "creation", "relationships", "economy"} == keys
    # 既定目標 seed で creation が重点
    assert body["goal"]["title"]
    assert body["focus_capital"] == "creation"
