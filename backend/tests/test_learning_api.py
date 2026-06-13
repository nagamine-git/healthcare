from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.scoring.timewindow import app_today


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


def test_initial_state(app_client):
    s = app_client.get("/api/learning/state").json()
    assert s["total"] == 21
    assert s["done_count"] == 0
    assert s["current_chapter"] == 1
    assert s["pace"] == "not_started"
    assert s["completed"] is False
    assert len(s["chapters"]) == 21
    # 山場フラグの確認 (4章 所有権)
    ch4 = next(c for c in s["chapters"] if c["chapter"] == 4)
    assert ch4["milestone"] is True


def test_three_point_completion(app_client):
    """読了だけでは complete にならない — 3 点セットで初めて章クリア。"""
    r = app_client.post("/api/learning/chapter/1/check", json={"field": "read", "done": True})
    assert r.status_code == 200
    s = r.json()
    ch1 = next(c for c in s["chapters"] if c["chapter"] == 1)
    assert ch1["read"] is True
    assert ch1["complete"] is False
    assert s["done_count"] == 0
    assert s["current_chapter"] == 1  # まだ 1 章のまま

    app_client.post("/api/learning/chapter/1/check", json={"field": "rustlings", "done": True})
    s = app_client.post(
        "/api/learning/chapter/1/check", json={"field": "explained", "done": True}
    ).json()
    ch1 = next(c for c in s["chapters"] if c["chapter"] == 1)
    assert ch1["complete"] is True
    assert s["done_count"] == 1
    assert s["current_chapter"] == 2  # 次の章へ進む


def test_check_writes_learning_domain_entry(app_client):
    """章チェックが当日の学習ドメイン達成度 (ライフスコア経路) に反映される。"""
    app_client.post("/api/learning/chapter/4/check", json={"field": "read", "done": True})
    today = app_today().isoformat()
    body = app_client.get("/api/domain/learning").json()
    entry = next(d for d in body["data"] if d["date"] == today)
    assert entry["achievement"] == 100.0
    assert "ch4" in entry["detail"]
    assert "読了" in entry["detail"]

    life = app_client.get("/api/life").json()
    learning = next(d for d in life["domains"] if d["key"] == "learning")
    assert learning["achievement"] == 100.0


def test_uncheck_reverts_field(app_client):
    app_client.post("/api/learning/chapter/2/check", json={"field": "read", "done": True})
    s = app_client.post(
        "/api/learning/chapter/2/check", json={"field": "read", "done": False}
    ).json()
    ch2 = next(c for c in s["chapters"] if c["chapter"] == 2)
    assert ch2["read"] is False


def test_unknown_chapter_and_field(app_client):
    assert (
        app_client.post("/api/learning/chapter/99/check", json={"field": "read", "done": True}).status_code
        == 404
    )
    assert (
        app_client.post("/api/learning/chapter/1/check", json={"field": "bogus", "done": True}).status_code
        == 422
    )


def test_activity_endpoint(app_client):
    """journey リポジトリの git hook 経路。"""
    r = app_client.post("/api/learning/activity", json={"detail": "journey: ch3 notes"})
    assert r.status_code == 200
    s = app_client.get("/api/learning/state").json()
    assert s["today"] is not None
    assert s["today"]["detail"] == "journey: ch3 notes"
    assert s["streak_sessions"] == 1


def test_llm_summary_shape(app_client):
    """LLM payload 用サマリが現在章と進捗を返す。"""
    from app.scoring.learning import llm_summary

    app_client.post("/api/learning/chapter/1/check", json={"field": "read", "done": True})
    s = llm_summary()
    assert s["progress"] == "0/21 章完了"
    assert s["current_chapter"]["chapter"] == 1
    assert s["current_chapter"]["checks"]["read"] is True
    assert s["today_done"] is True


def test_projection_estimates_completion(db_engine):
    from datetime import date, datetime, timedelta

    from app.db import session_scope
    from app.models import LearningSectionProgress
    from app.scoring.learning import TOTAL_SECTIONS, _progress_rows, projection

    today = date(2026, 6, 13)
    start = datetime(2026, 6, 1, 9, 0)
    # 節を5つ、最初の12日に分散して読了 (projection は節単位)
    with session_scope() as s:
        for i, sid in enumerate(["1.1", "1.2", "1.3", "3.1", "3.2"]):
            s.add(LearningSectionProgress(section_id=sid, done_at=start + timedelta(days=i * 3)))
    p = projection(_progress_rows(), today)
    assert p is not None
    assert p["done_units"] == 5
    assert p["total_units"] == TOTAL_SECTIONS
    assert p["started_on"] == "2026-06-01"
    assert p["eta_date"] is not None
    assert len(p["series"]) >= 1


def test_section_toggle(app_client):
    """節をトグルすると section_done が増え、章に節リストが付く。"""
    r = app_client.post("/api/learning/section/4.1/toggle", json={"done": True}).json()
    assert r["section_done"] == 1
    ch4 = next(c for c in r["chapters"] if c["chapter"] == 4)
    assert ch4["section_total"] == 3
    assert ch4["section_done"] == 1
    assert any(s["id"] == "4.1" and s["done"] for s in ch4["sections"])
    # 不正な節は 404
    assert app_client.post("/api/learning/section/99.9/toggle", json={"done": True}).status_code == 404
