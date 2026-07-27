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


# --- _gather_context: exercise_sets 有無でコンテキストが分岐する -----------------


def _add_strength_workout(session, wid, start, exercise_sets=None):
    from app.models import Workout

    raw_json = {"activityId": 1} if exercise_sets is None else {
        "activityId": 1, "exercise_sets": exercise_sets,
    }
    session.add(Workout(
        id=wid, source="garmin", start=start, end=start + timedelta(minutes=15),
        type="strength_training", duration_s=900, avg_hr=110.0, max_hr=140.0,
        raw_json=raw_json,
    ))
    session.commit()


SAMPLE_SETS = {
    "sets": [
        {"category": "ROW", "name": None, "reps": 8, "weight_kg": 12.0,
         "duration_s": 59.3, "start": "2026-07-26T08:09:21.0"},
        {"category": "ROW", "name": None, "reps": 8, "weight_kg": 12.0,
         "duration_s": 39.4, "start": "2026-07-26T08:11:24.0"},
        {"category": "CURL", "name": None, "reps": 6, "weight_kg": 8.0,
         "duration_s": 24.0, "start": "2026-07-26T08:19:55.0"},
    ]
}


def test_gather_context_includes_exercise_detail_when_present(app_client, session):
    """exercise_sets があれば種目単位のボリューム/rep レンジ + 既往情報 + 直近セッションを渡す。"""
    from app.llm.workout_review import _gather_context

    _add_strength_workout(
        session, "w-prev", datetime.utcnow() - timedelta(days=3), exercise_sets=SAMPLE_SETS
    )
    _add_strength_workout(
        session, "w-today", datetime.utcnow() - timedelta(hours=1), exercise_sets=SAMPLE_SETS
    )

    ctx = _gather_context("w-today")
    assert ctx is not None
    exercises = ctx["workout"]["exercises"]
    assert {e["category"] for e in exercises} == {"ROW", "CURL"}
    row = next(e for e in exercises if e["category"] == "ROW")
    assert row["set_count"] == 2
    assert row["rep_range"] == [8, 8]
    assert row["volume_kg"] == 12.0 * 8 * 2

    assert "user_injury_notes" in ctx
    assert any("腰" in note for note in ctx["user_injury_notes"])

    assert len(ctx["recent_exercise_sessions"]) == 1
    assert ctx["recent_exercise_sessions"][0]["exercises"][0]["category"] == "ROW"


def test_gather_context_falls_back_when_no_exercise_sets(app_client, session):
    """exercise_sets が無い (未対応/古いワークアウト) 場合は従来どおりのコンテキストのまま
    種目情報を捏造しない (workout.exercises / recent_exercise_sessions が乗らない)。"""
    from app.llm.workout_review import _gather_context

    _add_strength_workout(session, "w-plain", datetime.utcnow() - timedelta(hours=1))

    ctx = _gather_context("w-plain")
    assert ctx is not None
    assert "exercises" not in ctx["workout"]
    assert "recent_exercise_sessions" not in ctx
    assert "user_injury_notes" not in ctx
