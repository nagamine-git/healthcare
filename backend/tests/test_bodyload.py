from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.db import session_scope
from app.models import Workout
from app.scoring import bodyload


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


def _add(session, wid, type_, start, load=50.0, raw=None):
    session.add(Workout(
        id=wid, source="garmin", start=start, type=type_,
        duration_s=1800, training_load=load, raw_json=raw,
    ))


def test_no_workouts_surfaces_all_as_gap(db_engine):
    now = datetime(2026, 6, 13, 0, 0)
    s = bodyload.state(now=now)
    assert {g["key"] for g in s["groups"]} == {"shoulders", "pull", "core", "push", "legs"}
    # 刺激ゼロ → 全群 confidence=none・回復100%・おすすめは美的重み順 (肩/背中が上位)
    assert all(g["confidence"] == "none" for g in s["groups"])
    assert all(g["recovery_pct"] == 100 for g in s["groups"])
    assert s["confidence"] == "none"
    top = {x["key"] for x in s["suggestion"]}
    assert top == {"shoulders", "pull"}


def test_boxing_stimulates_shoulders_not_back(db_engine):
    now = datetime(2026, 6, 13, 0, 0)
    with session_scope() as session:
        _add(session, "w1", "boxing", now - timedelta(hours=6), load=80)
    s = bodyload.state(now=now)
    g = {x["key"]: x for x in s["groups"]}
    # 肩は6h前に刺激 → 回復途中・inferred
    assert g["shoulders"]["confidence"] == "inferred"
    assert g["shoulders"]["recovery_pct"] < 100
    assert g["shoulders"]["last_at"] is not None
    # 背中 (引く) はボクシングでは関与<0.4 → 刺激なし扱い (背中ギャップ)
    assert g["pull"]["confidence"] == "none"
    # 直近で肩を叩いた直後なので、おすすめは背中側が上位に来る
    assert s["suggestion"][0]["key"] in {"pull", "legs", "push", "core"}


def test_exercise_sets_give_measured_confidence(db_engine):
    now = datetime(2026, 6, 13, 0, 0)
    raw = {"summarizedExerciseSets": [
        {"category": "PULL_UP"}, {"category": "BENCH_PRESS"},
    ]}
    with session_scope() as session:
        _add(session, "w1", "strength_training", now - timedelta(hours=10), load=90, raw=raw)
    s = bodyload.state(now=now)
    g = {x["key"]: x for x in s["groups"]}
    assert g["pull"]["confidence"] == "measured"
    assert g["push"]["confidence"] == "measured"
    assert s["confidence"] == "high"


def test_recovered_group_preferred_in_suggestion(db_engine):
    now = datetime(2026, 6, 13, 0, 0)
    with session_scope() as session:
        # 肩を直前に高負荷 (回復前) / 脚は5日前 (回復済み)
        _add(session, "w1", "boxing", now - timedelta(hours=2), load=100)
        _add(session, "w2", "running", now - timedelta(days=5), load=100)
    s = bodyload.state(now=now)
    g = {x["key"]: x for x in s["groups"]}
    assert g["shoulders"]["recovery_pct"] < 60  # まだ痛い
    assert g["legs"]["recovery_pct"] == 100
    # 痛い肩はおすすめから外れる
    assert "shoulders" not in {x["key"] for x in s["suggestion"]}


def test_bodyload_api(app_client):
    body = app_client.get("/api/bodyload").json()
    assert "groups" in body and len(body["groups"]) == 5
    assert "suggestion" in body
