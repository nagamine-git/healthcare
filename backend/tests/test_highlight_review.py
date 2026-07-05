"""ハイライトイベント評価 API のテスト (LLM は monkeypatch)。"""

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


def _mock_llm(monkeypatch, calls):
    async def fake(*, target, label, time_jst, sub):
        calls["n"] += 1
        return {"text": f"{label}: 睡眠5.8hは筋合成にやや不足。7hを狙って。", "tone": "caution", "model": "test"}

    import app.llm.highlight_review as hr

    monkeypatch.setattr(hr, "generate_review", fake)


def test_create_persist_idempotent_and_list(app_client, monkeypatch):
    calls = {"n": 0}
    _mock_llm(monkeypatch, calls)
    body = {"date": "2026-07-05", "event_key": "01:32|就寝", "label": "就寝", "time_jst": "01:32"}

    r1 = app_client.post("/api/highlight-reviews", json=body)
    assert r1.status_code == 200 and r1.json()["tone"] == "caution" and calls["n"] == 1

    r2 = app_client.post("/api/highlight-reviews", json=body)  # 冪等
    assert r2.status_code == 200 and calls["n"] == 1

    r3 = app_client.post("/api/highlight-reviews", json={**body, "force": True})
    assert r3.status_code == 200 and calls["n"] == 2

    lst = app_client.get("/api/highlight-reviews").json()["items"]
    assert any(i["event_key"] == "01:32|就寝" and i["date"] == "2026-07-05" for i in lst)


def test_same_key_different_date_is_separate(app_client, monkeypatch):
    calls = {"n": 0}
    _mock_llm(monkeypatch, calls)
    a = {"date": "2026-07-04", "event_key": "20:59|ランニング", "label": "ランニング"}
    b = {"date": "2026-07-05", "event_key": "20:59|ランニング", "label": "ランニング"}
    assert app_client.post("/api/highlight-reviews", json=a).status_code == 200
    assert app_client.post("/api/highlight-reviews", json=b).status_code == 200
    assert calls["n"] == 2


def test_invalid_date_400(app_client):
    r = app_client.post("/api/highlight-reviews", json={"date": "not-a-date", "event_key": "x", "label": "x"})
    assert r.status_code == 400
