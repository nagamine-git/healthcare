"""予定 (到着時刻) からの逆算。"""

from __future__ import annotations

from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.scoring.appointment_plan import plan_from_appointment


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

JST = ZoneInfo("Asia/Tokyo")
D = date(2026, 8, 20)


def test_backcalculates_wake_from_arrival():
    """到着 − 移動 − 身支度 = 布団を出る時刻。"""
    got = plan_from_appointment(D, "09:00", travel_min=60, prep_min=45, tz=JST)
    assert got["arrive"] == "09:00"
    assert got["depart"] == "08:00"   # 09:00 − 60分
    assert got["wake"] == "07:15"     # 08:00 − 45分
    assert got["wake_time"] == "07:15"  # override にそのまま入る値


def test_rejects_when_it_spills_into_the_previous_day():
    """前日にはみ出す逆算は**黙って通さない**。

    SleepPlanOverride は HH:MM しか持たないので、前日にはみ出した値をそのまま入れると
    24時間ずれた計画になり、静かに間違った就寝時刻を提示してしまう。
    """
    with pytest.raises(ValueError, match="前泊"):
        plan_from_appointment(D, "05:00", travel_min=300, prep_min=45, tz=JST)


def test_rejects_absurd_inputs():
    """打ち間違いを弾く (0 は許す: 移動なし・身支度なしは有効な入力)。"""
    for kwargs in ({"travel_min": 13 * 60, "prep_min": 45}, {"travel_min": 30, "prep_min": 7 * 60}):
        with pytest.raises(ValueError):
            plan_from_appointment(D, "09:00", tz=JST, **kwargs)
    got = plan_from_appointment(D, "09:00", travel_min=0, prep_min=0, tz=JST)
    assert got["wake"] == "09:00"


def test_api_applies_override_and_returns_plan(app_client):
    """API は上書きを保存し、その日の計画ごと返す (就寝等は既存の逆算が追随する)。"""
    from app.scoring.timewindow import app_today

    target = app_today() + timedelta(days=1)
    r = app_client.post("/api/sleep-plan/from-appointment", json={
        "date": target.isoformat(), "arrive_at": "08:30",
        "travel_min": 45, "prep_min": 40, "place": "オフィス",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["depart"] == "07:45"
    assert body["wake"] == "07:05"
    assert body["applied"] is True
    assert body["place"] == "オフィス"
    # 上書きが実際に保存され、GET でも読める
    got = app_client.get(f"/api/sleep-plan/override?date={target.isoformat()}").json()
    assert got["override"]["wake_time"] == "07:05"
    # 計画一式が付いてくる (呼び出し側が就寝時刻を再計算しないで済む)
    assert "in_bed" in body["plan"] and "hard_deadlines" in body["plan"]


def test_api_can_preview_without_saving(app_client):
    """apply=false なら保存しない (試算だけ)。"""
    from app.scoring.timewindow import app_today

    target = app_today() + timedelta(days=2)
    r = app_client.post("/api/sleep-plan/from-appointment", json={
        "date": target.isoformat(), "arrive_at": "10:00", "travel_min": 30, "apply": False,
    })
    assert r.status_code == 200
    assert r.json()["applied"] is False
    assert app_client.get(f"/api/sleep-plan/override?date={target.isoformat()}").json()["override"] is None


def test_api_rejects_previous_day_spill_with_400(app_client):
    r = app_client.post("/api/sleep-plan/from-appointment", json={
        "arrive_at": "04:00", "travel_min": 360, "prep_min": 60,
    })
    assert r.status_code == 400
    assert "前泊" in r.json()["detail"]
