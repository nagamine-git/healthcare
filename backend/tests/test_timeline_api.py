from __future__ import annotations

from datetime import date as date_type
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.scoring.timewindow import app_today, jst_day_bounds


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


def test_timeline_aggregates_day_in_jst_hours(app_client):
    from app.db import session_scope
    from app.models import (
        BodyBattery,
        CaffeineIntake,
        MetricSample,
        SleepSession,
        Workout,
    )

    today = app_today()
    start, _ = jst_day_bounds(today)
    with session_scope() as s:
        # JST 09:00 の BB (start = JST 00:00 の UTC naive)
        s.add(BodyBattery(ts=start + timedelta(hours=9), value=70.0))
        s.add(MetricSample(source="garmin", metric_key="stress",
                           ts=start + timedelta(hours=10), value=42.0))
        s.add(MetricSample(source="garmin", metric_key="sleep_midpoint_hour",
                           ts=start + timedelta(hours=7), value=3.5))
        s.add(SleepSession(date=today, source="garmin", total_min=420))
        s.add(Workout(id="w1", source="garmin", start=start + timedelta(hours=20),
                      end=start + timedelta(hours=20, minutes=30), type="strength_training"))
        s.add(CaffeineIntake(ts=start + timedelta(hours=8, minutes=30), source="green_tea",
                             amount=1.0, unit="杯", mg=30.0))

    body = app_client.get("/api/timeline").json()
    assert body["date"] == today.isoformat()
    assert body["body_battery"][0]["h"] == 9.0
    assert body["stress"][0]["v"] == 42.0
    # 睡眠: 中点 3.5h ± 3.5h (420分) = 0.0-7.0
    assert body["sleep_blocks"] == [{"start_h": 0.0, "end_h": 7.0}]
    assert body["workouts"][0]["start_h"] == 20.0
    assert body["caffeine"][0]["mg"] == 30.0
    assert body["migraine"] == []


def test_timeline_empty_day(app_client):
    body = app_client.get("/api/timeline").json()
    assert body["body_battery"] == []
    assert body["sleep_blocks"] == []
    assert body["checkin"] is None


def test_timeline_24h_window(app_client):
    """直近24時間ウィンドウは date を持たず origin/span/now を返す。"""
    body = app_client.get("/api/timeline?window=24h").json()
    assert body["window"] == "24h"
    assert body["date"] is None
    assert body["span_h"] == 24.0
    assert body["now_h"] == 21.0  # 過去21h+未来3h。現在は offset 21
    assert "origin_jst" in body


def test_day_story_stats_falls_back_to_daily_summary_when_hae_empty(app_client):
    """HAE (Apple Health) の step_count/active_energy が無い日は Garmin
    DailySummary の合計を使う (取り込みが止まっても 0 表示にならない)。"""
    from app.db import session_scope
    from app.models import DailySummary

    target = date_type(2026, 5, 21)
    with session_scope() as s:
        s.add(DailySummary(date=target, steps=2535, active_kcal=47.0))

    body = app_client.get("/api/day-story?date=2026-05-21").json()
    assert body["stats"]["steps"] == 2535
    assert body["stats"]["active_kcal"] == 47


def test_day_story_stats_prefers_hae_when_present(app_client):
    """HAE 側にデータがあれば Garmin DailySummary の値より優先される。"""
    from app.db import session_scope
    from app.models import DailySummary, MetricSample

    target = date_type(2026, 5, 22)
    start, _ = jst_day_bounds(target)
    with session_scope() as s:
        for m in range(0, 60, 15):
            s.add(MetricSample(source="hae", metric_key="step_count",
                               ts=start + timedelta(hours=10, minutes=m), value=100.0))
        s.add(MetricSample(source="hae", metric_key="active_energy",
                           ts=start + timedelta(hours=10), value=25.0))
        # DailySummary にも値があるが、HAE が生きているのでこちらは無視される
        s.add(DailySummary(date=target, steps=99999, active_kcal=999.0))

    body = app_client.get("/api/day-story?date=2026-05-22").json()
    assert body["stats"]["steps"] == 400
    assert body["stats"]["active_kcal"] == 25


def test_day_story_24h_window_falls_back_to_daily_summary(app_client):
    """window=24h は当日+前日にまたがりうる。当日分は按分せず全量、前日分は
    重なり時間/24hで按分するので、合計は当日単独の値以上・単純合算以下になる。"""
    from app.db import session_scope
    from app.models import DailySummary
    from app.scoring.timewindow import app_today

    today = app_today()
    yesterday = today - timedelta(days=1)
    with session_scope() as s:
        s.add(DailySummary(date=today, steps=2535, active_kcal=47.0))
        s.add(DailySummary(date=yesterday, steps=4444, active_kcal=98.0))

    body = app_client.get("/api/day-story?window=24h").json()
    assert 2535 <= body["stats"]["steps"] <= 2535 + 4444
    assert 47 <= body["stats"]["active_kcal"] <= 47 + 98


def test_day_story_infers_segments(app_client):
    from app.db import session_scope
    from app.models import MetricSample, SleepSession, Workout

    # 固定の過去日付で検証 (今日だと now_h より後ろの seed が未来扱いで除外され、
    # 実行時刻に依存してしまう)
    today = date_type(2026, 5, 20)
    start, _ = jst_day_bounds(today)
    with session_scope() as s:
        s.add(SleepSession(date=today, source="garmin", total_min=420))
        s.add(MetricSample(source="garmin", metric_key="sleep_midpoint_hour",
                           ts=start + timedelta(hours=7), value=3.5))
        s.add(MetricSample(source="garmin", metric_key="resting_heart_rate",
                           ts=start + timedelta(hours=15), value=50.0))
        # 10時台に活発な歩行 (外出)
        for m in range(0, 60, 5):
            s.add(MetricSample(source="hae", metric_key="step_count",
                               ts=start + timedelta(hours=10, minutes=m), value=120.0))
        # 14時台は座位・低ストレス (休息)
        s.add(MetricSample(source="garmin", metric_key="stress",
                           ts=start + timedelta(hours=14, minutes=30), value=20.0))
        s.add(Workout(id="w1", source="garmin", start=start + timedelta(hours=20),
                      end=start + timedelta(hours=20, minutes=30), type="boxing"))

    body = app_client.get("/api/day-story?date=2026-05-20").json()
    labels = {seg["label"] for seg in body["segments"]}
    assert "睡眠" in labels
    assert "ボクシング" in labels
    assert any("外出" in lab or "移動" in lab for lab in labels)
    assert "の1日" in body["summary"]
    assert "insights" in body and isinstance(body["insights"], list)
