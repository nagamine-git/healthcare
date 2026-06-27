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


def test_entry_upsert_and_list_and_delete(app_client):
    r = app_client.put("/api/journal/entry", json={"date": "2026-06-27", "text": "テスト日記"})
    assert r.status_code == 200
    assert r.json()["entries"][0]["text"] == "テスト日記"
    # 同一日付は upsert
    app_client.put("/api/journal/entry", json={"date": "2026-06-27", "text": "更新"})
    entries = app_client.get("/api/journal/entries").json()["entries"]
    assert len(entries) == 1 and entries[0]["text"] == "更新"
    # 削除
    d = app_client.delete("/api/journal/entry/2026-06-27")
    assert d.status_code == 200
    assert d.json()["entries"] == []


def test_transcribe_uses_llm(app_client, monkeypatch):
    import app.api.journal as japi

    async def fake(**kwargs):
        return "# 起こした本文\n- 感謝: [?]"

    monkeypatch.setattr(japi, "transcribe_journal", fake)
    r = app_client.post("/api/journal/transcribe", json={"image_base64": "x"})
    assert r.status_code == 200
    assert "起こした本文" in r.json()["text"]
