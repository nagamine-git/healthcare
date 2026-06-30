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


def test_consult_returns_reply(app_client, monkeypatch):
    import app.api.consult as capi

    captured = {}

    async def fake_consult(messages):
        captured["messages"] = messages
        return "タンパク質は体重×2g/日が目安です。"

    monkeypatch.setattr(capi, "consult", fake_consult)
    r = app_client.post("/api/consult", json={"messages": [{"role": "user", "content": "朝のサプリ最適量は?"}]})
    assert r.status_code == 200
    assert "タンパク質" in r.json()["reply"]
    assert captured["messages"][0]["content"] == "朝のサプリ最適量は?"


def test_consult_context_builds_without_error(db_engine):
    # 空 DB でも文脈アセンブラが例外を出さない(各 gather は失敗時 None)
    from datetime import date

    from app.llm.client import gather_consult_context

    ctx = gather_consult_context(date(2026, 6, 30))
    assert "profile" in ctx and "body_composition" in ctx
