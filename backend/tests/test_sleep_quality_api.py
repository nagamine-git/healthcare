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


def test_wake_stages_none_when_raw_json_missing(app_client):
    """raw_json が無い (=Apple Health 由来など) 夜は wake_stages が None になり 500 にしない。"""
    _seed_sleep(raw_json=None)
    resp = app_client.get("/api/sleep/last-night")
    assert resp.status_code == 200, resp.text
    assert resp.json()["wake_stages"] is None


def test_wake_stages_detects_actual_wake(app_client):
    """sleepMovement から体動起床を検出できれば、目覚め/起床の両方を JST HH:MM で返す。"""
    from datetime import UTC, datetime, timedelta
    from zoneinfo import ZoneInfo

    from app.scoring.timewindow import app_today

    jst = ZoneInfo("Asia/Tokyo")
    target = app_today()
    sleep_end_jst = datetime.combine(target, datetime.min.time(), jst).replace(hour=7, minute=0)
    actual_wake_jst = sleep_end_jst + timedelta(minutes=20)
    epoch_ms = int(sleep_end_jst.astimezone(UTC).timestamp() * 1000)

    def entry(dt, level):
        s = dt.astimezone(UTC).replace(tzinfo=None)
        e = s + timedelta(minutes=1)
        return {
            "startGMT": s.strftime("%Y-%m-%dT%H:%M:%S.0"),
            "endGMT": e.strftime("%Y-%m-%dT%H:%M:%S.0"),
            "activityLevel": level,
        }

    movement = [entry(sleep_end_jst + timedelta(minutes=i), 2.0) for i in range(20)]
    movement += [entry(actual_wake_jst + timedelta(minutes=i), 6.0) for i in range(3)]

    _seed_sleep(raw_json={
        "dailySleepDTO": {"sleepEndTimestampGMT": epoch_ms},
        "sleepMovement": movement,
    })
    resp = app_client.get("/api/sleep/last-night")
    assert resp.status_code == 200, resp.text
    ws = resp.json()["wake_stages"]
    assert ws["sleep_end_hhmm"] == "07:00"
    assert ws["actual_wake_hhmm"] == "07:20"
    assert ws["lingering_min"] == 20
