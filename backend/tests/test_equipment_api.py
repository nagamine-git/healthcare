"""器具 CRUD API (settings からの自動シード含む)。"""

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


def test_seed_toggle_add_delete(app_client):
    r = app_client.get("/api/equipment")
    items = r.json()["items"]
    assert len(items) > 0  # settings.user_equipment からシード
    # 1つ無効化 → resolve から消える想定 (available=False)
    first = items[0]
    r2 = app_client.post("/api/equipment", json={**first, "available": False})
    assert any(i["id"] == first["id"] and i["available"] is False for i in r2.json()["items"])
    # 追加
    r3 = app_client.post("/api/equipment", json={"name": "ケトルベル 12kg"})
    assert any(i["name"] == "ケトルベル 12kg" for i in r3.json()["items"])
    # 削除
    kid = next(i["id"] for i in r3.json()["items"] if i["name"] == "ケトルベル 12kg")
    r4 = app_client.delete(f"/api/equipment/{kid}")
    assert all(i["id"] != kid for i in r4.json()["items"])
