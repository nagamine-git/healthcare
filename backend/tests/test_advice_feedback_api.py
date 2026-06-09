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


def test_post_feedback_upsert(app_client):
    r = app_client.post("/api/advice/feedback", json={
        "action_key": "水分 500ml 補給", "done": True, "rating": 1, "category": "nutrition"})
    assert r.status_code == 200
    body = r.json()
    fb = body["feedback"]["水分 500ml 補給"]
    assert fb["done"] is True and fb["rating"] == 1

    # 部分更新: rating だけ変える → done 保持
    r2 = app_client.post("/api/advice/feedback", json={"action_key": "水分 500ml 補給", "rating": -1})
    fb2 = r2.json()["feedback"]["水分 500ml 補給"]
    assert fb2["done"] is True and fb2["rating"] == -1


def test_rating_out_of_range_rejected(app_client):
    assert app_client.post("/api/advice/feedback", json={"action_key": "x", "rating": 2}).status_code == 422


def test_feedback_attached_to_today_advice(app_client):
    """/api/today の advice に当日フィードバックが付く。"""
    from datetime import date

    from app.db import session_scope
    from app.models import LlmComment

    today = date.today()
    with session_scope() as s:
        s.add(LlmComment(
            date=today, generated_at=__import__("datetime").datetime.now(),
            model="test", prompt_hash="h", comment="c",
            payload={"focus": "f", "rationale": "r",
                     "actions": [{"title": "散歩 15分", "time_jst": "12:00",
                                  "duration_min": 15, "category": "cardio", "priority": "mid"}]},
        ))
    app_client.post("/api/advice/feedback", json={"action_key": "散歩 15分", "done": True})
    body = app_client.get("/api/today").json()
    assert body["advice"]["feedback"]["散歩 15分"]["done"] is True
