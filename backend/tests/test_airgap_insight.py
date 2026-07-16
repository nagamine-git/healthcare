from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.scoring.airgap_insight import compute_airgap_sleep_insight


def test_not_enough_data_returns_unavailable():
    rows = [{"waste_min": 10, "sleep_sub": 80, "hrv_sub": 70}] * 4  # 各群2日 < 5
    out = compute_airgap_sleep_insight(rows)
    assert out["available"] is False
    assert out["days_analyzed"] == 4


def test_splits_by_rank_and_computes_diff():
    # 低浪費5日 (sleep高め) + 高浪費5日 (sleep低め)
    rows = [{"waste_min": w, "sleep_sub": 90.0, "hrv_sub": 60.0} for w in [5, 10, 15, 20, 25]]
    rows += [{"waste_min": w, "sleep_sub": 60.0, "hrv_sub": 40.0} for w in [80, 90, 100, 110, 120]]
    out = compute_airgap_sleep_insight(rows)
    assert out["available"] is True
    assert out["days_analyzed"] == 10
    assert out["days_per_group"] == 5
    assert out["sleep_low"] == 90.0
    assert out["sleep_high"] == 60.0
    assert out["sleep_diff"] == -30.0  # 高浪費日は睡眠スコアが低い
    assert out["hrv_diff"] == -20.0


def test_odd_count_drops_middle_row():
    rows = [{"waste_min": w, "sleep_sub": 50.0, "hrv_sub": 50.0} for w in range(11)]  # 11日
    out = compute_airgap_sleep_insight(rows)
    assert out["days_analyzed"] == 11
    assert out["days_per_group"] == 5  # 11//2 = 5 (中央の1日は不使用)


def test_missing_subscores_are_excluded_from_average():
    rows = [{"waste_min": w, "sleep_sub": None, "hrv_sub": 50.0} for w in range(10)]
    out = compute_airgap_sleep_insight(rows)
    assert out["sleep_low"] is None
    assert out["sleep_diff"] is None
    assert out["hrv_diff"] == 0.0


@pytest.fixture
def app_client(temp_data_dir, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(temp_data_dir))
    monkeypatch.setenv("HAE_INGEST_TOKEN", "test-token")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")

    from app import main as main_module
    from app.config import Settings, reset_settings_cache

    reset_settings_cache()
    settings = Settings(scheduler_enabled=False, app_data_dir=temp_data_dir)
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)

    app = main_module.create_app()
    with TestClient(app) as client:
        yield client


def test_insight_endpoint_unavailable_when_no_data(app_client):
    r = app_client.get("/api/airgap/insight")
    assert r.status_code == 200
    assert r.json()["available"] is False


def test_insight_endpoint_available_with_enough_joined_data(app_client):
    from datetime import datetime, timedelta

    from app.db import session_scope
    from app.models import AirgapDaily, DailyScore
    from app.scoring.timewindow import app_today

    today = app_today()
    with session_scope() as s:
        for i in range(10):
            d = today - timedelta(days=i)
            waste = 10 if i < 5 else 100
            sleep = 90.0 if i < 5 else 55.0
            s.add(AirgapDaily(date=d, score=70, completed_min=30, failures=0, goal_min=60,
                              waste_min=waste, waste_limit_min=60, sessions=1,
                              updated_at=datetime.utcnow()))
            s.add(DailyScore(date=d, sleep_sub=sleep, hrv_sub=50.0, version="v1",
                             computed_at=datetime.utcnow()))
    r = app_client.get("/api/airgap/insight")
    d = r.json()
    assert d["available"] is True
    assert d["days_analyzed"] == 10
    assert d["sleep_diff"] < 0
