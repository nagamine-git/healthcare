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


def _check(client, sid, field, done=True):
    return client.post(f"/api/learning/section/{sid}/check", json={"field": field, "done": done})


def test_three_point_completion(app_client):
    """節は 3 点セットで初めて complete。章は全節 complete で初めてクリア。"""
    # 1 章は 1.1 / 1.2 / 1.3 の 3 節。1.1 を読了だけ → まだ未完
    r = _check(app_client, "1.1", "read")
    assert r.status_code == 200
    s = r.json()
    ch1 = next(c for c in s["chapters"] if c["chapter"] == 1)
    sec = next(x for x in ch1["sections"] if x["id"] == "1.1")
    assert sec["read"] is True
    assert sec["done"] is False
    assert ch1["complete"] is False
    assert s["section_done"] == 0
    assert s["current_chapter"] == 1

    # 1 章の全 3 節 × 3 点を埋めると章クリア
    for sid in ("1.1", "1.2", "1.3"):
        for field in ("read", "rustlings", "explained"):
            s = _check(app_client, sid, field).json()
    ch1 = next(c for c in s["chapters"] if c["chapter"] == 1)
    assert ch1["complete"] is True
    assert s["done_count"] == 1
    assert s["current_chapter"] == 2  # 次の章へ進む


def test_check_writes_learning_domain_entry(app_client):
    """節チェックが当日の学習ドメイン達成度 (ライフスコア経路) に反映される。"""
    _check(app_client, "4.1", "read")
    today = app_today().isoformat()
    body = app_client.get("/api/domain/learning").json()
    entry = next(d for d in body["data"] if d["date"] == today)
    assert entry["achievement"] == 100.0
    assert "4.1" in entry["detail"]
    assert "読了" in entry["detail"]

    life = app_client.get("/api/life").json()
    learning = next(d for d in life["domains"] if d["key"] == "learning")
    assert learning["achievement"] == 100.0


def test_uncheck_reverts_field(app_client):
    _check(app_client, "2", "read")
    s = _check(app_client, "2", "read", done=False).json()
    ch2 = next(c for c in s["chapters"] if c["chapter"] == 2)
    sec = next(x for x in ch2["sections"] if x["id"] == "2")
    assert sec["read"] is False


def test_unknown_section_and_field(app_client):
    assert _check(app_client, "99.9", "read").status_code == 404
    assert (
        app_client.post("/api/learning/section/1.1/check", json={"field": "bogus", "done": True}).status_code
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

    _check(app_client, "1.1", "read")
    s = llm_summary()
    assert s["progress"] == "0/21 章完了"
    assert s["current_chapter"]["chapter"] == 1
    # 章の read は全節が read で初めて True。1.1 だけなのでまだ False
    assert s["current_chapter"]["checks"]["read"] is False
    assert s["today_done"] is True


def test_projection_estimates_completion(db_engine):
    from datetime import date, datetime, timedelta

    from app.db import session_scope
    from app.models import LearningSectionProgress
    from app.scoring.learning import TOTAL_CHECKS, projection

    today = date(2026, 6, 13)
    start = datetime(2026, 6, 1, 0, 0)
    # 節を5つ、最初の12日に分散して読了 (projection はチェック単位)
    with session_scope() as s:
        for i, sid in enumerate(["1.1", "1.2", "1.3", "3.1", "3.2"]):
            s.add(LearningSectionProgress(section_id=sid, read_at=start + timedelta(days=i * 3)))
    p = projection(today)
    assert p is not None
    assert p["done_units"] == 5
    assert p["total_units"] == TOTAL_CHECKS
    assert p["started_on"] == "2026-06-01"
    assert p["eta_date"] is not None
    # ±0.7 帯: best (好調) は normal より早く、worst (不調) は遅い
    assert p["eta_best"] <= p["eta_normal"] <= p["eta_worst"]
    assert len(p["series"]) >= 1


def test_section_check(app_client):
    """節は 3 点揃って done。section_done は完了節数を数える。"""
    # 4.1 を読了だけ → section_done はまだ 0 (3 点未達)
    r = _check(app_client, "4.1", "read").json()
    assert r["section_done"] == 0
    ch4 = next(c for c in r["chapters"] if c["chapter"] == 4)
    assert ch4["section_total"] == 3
    sec = next(x for x in ch4["sections"] if x["id"] == "4.1")
    assert sec["read"] is True and sec["done"] is False

    # 3 点揃えると done
    _check(app_client, "4.1", "rustlings")
    r = _check(app_client, "4.1", "explained").json()
    assert r["section_done"] == 1
    ch4 = next(c for c in r["chapters"] if c["chapter"] == 4)
    assert ch4["section_done"] == 1
    assert any(s["id"] == "4.1" and s["done"] for s in ch4["sections"])
    # 不正な節は 404
    assert _check(app_client, "99.9", "read").status_code == 404
