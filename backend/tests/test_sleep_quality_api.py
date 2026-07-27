"""GET /api/sleep/last-night の API 層テスト。

回帰テスト: 純関数 (`scoring/sleep_quality.py`) のテストだけでは
**API 層で ORM オブジェクトを session_scope の外へ持ち出して
DetachedInstanceError → 500** になる不具合を検出できず、本番で初めて発覚した。
実 DB を通す経路を必ず1本張っておく。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_client(temp_data_dir, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(temp_data_dir))
    monkeypatch.setenv("HAE_INGEST_TOKEN", "test")

    from app import main as main_module
    from app.config import Settings, reset_settings_cache

    reset_settings_cache()
    settings = Settings(scheduler_enabled=False, app_data_dir=temp_data_dir)
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)

    app = main_module.create_app()
    with TestClient(app) as client:
        yield client


def _seed_sleep(**over):
    """今日 (= 起床日) の SleepSession を1件入れる。"""
    from app.db import session_scope
    from app.models import SleepSession
    from app.scoring.timewindow import app_today

    row = {
        "date": app_today(), "source": "garmin", "total_min": 371,
        "deep_min": 93, "rem_min": 51, "light_min": 227, "awake_min": 1,
        "sleep_score": 74.0,
    }
    row.update(over)
    with session_scope() as s:
        s.add(SleepSession(**row))


def test_last_night_returns_evaluation(app_client):
    """実 DB 経由で 200 と評価が返ること (DetachedInstanceError の回帰)。"""
    _seed_sleep()
    resp = app_client.get("/api/sleep/last-night")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["available"] is True
    keys = {c["key"] for c in body["components"]}
    assert {"deep", "rem"} <= keys
    # 実データ相当 (deep 93/371=25% 良好, rem 51/371=14% 低い)
    by = {c["key"]: c for c in body["components"]}
    assert by["deep"]["status"] == "good"
    assert by["rem"]["status"] == "low"


def test_last_night_without_data_is_unavailable(app_client):
    """睡眠データが無い日は available:false (500 にしない)。"""
    resp = app_client.get("/api/sleep/last-night")
    assert resp.status_code == 200, resp.text
    assert resp.json()["available"] is False


def test_last_night_with_null_total_is_unavailable(app_client):
    """total_min が欠測でも 500 にせず available:false。"""
    _seed_sleep(total_min=None, deep_min=None, rem_min=None)
    resp = app_client.get("/api/sleep/last-night")
    assert resp.status_code == 200, resp.text
    assert resp.json()["available"] is False


def test_updated_at_not_required(app_client):
    """seed に updated_at を持たない SleepSession でも動く (モデル差異の保険)。"""
    _seed_sleep(sleep_score=None)
    assert app_client.get("/api/sleep/last-night").status_code == 200
