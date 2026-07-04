"""ワークアウト一言評価 API のテスト (LLM は monkeypatch)。"""

from __future__ import annotations

from datetime import datetime, timedelta

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


def _add_workout(session, wid="w1", wtype="running"):
    from app.models import Workout

    session.add(Workout(
        id=wid, source="garmin", start=datetime.utcnow() - timedelta(hours=2),
        end=datetime.utcnow() - timedelta(hours=1, minutes=45),
        type=wtype, duration_s=900, distance_m=2400.0, avg_hr=155.0, max_hr=183.0,
    ))
    session.commit()


def test_list_empty(app_client):
    r = app_client.get("/api/workout-reviews")
    assert r.status_code == 200
    assert r.json()["items"] == []


def test_generate_persist_and_idempotent(app_client, session, monkeypatch):
    _add_workout(session)
    calls = {"n": 0}

    async def fake_generate(workout_id):
        calls["n"] += 1
        return {"text": "GPS未捕捉で距離が出ていません。次回は捕捉を待ってから。", "tone": "caution", "model": "test"}

    import app.llm.workout_review as wr

    monkeypatch.setattr(wr, "generate_review", fake_generate)

    r1 = app_client.post("/api/workout-reviews/w1")
    assert r1.status_code == 200
    assert r1.json()["review_tone"] == "caution"
    assert calls["n"] == 1

    # 冪等: 2回目は再生成しない
    r2 = app_client.post("/api/workout-reviews/w1")
    assert r2.status_code == 200 and calls["n"] == 1

    # force で再生成
    r3 = app_client.post("/api/workout-reviews/w1?force=1")
    assert r3.status_code == 200 and calls["n"] == 2

    # 一覧に保存済み評価が乗る
    r4 = app_client.get("/api/workout-reviews")
    item = next(i for i in r4.json()["items"] if i["workout_id"] == "w1")
    assert "GPS未捕捉" in item["review_text"]
    assert item["type_label"] == "ランニング"


def test_unknown_workout_404(app_client):
    r = app_client.post("/api/workout-reviews/nope")
    assert r.status_code == 404
