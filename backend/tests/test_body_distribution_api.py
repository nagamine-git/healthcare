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


def test_distribution_shape(app_client):
    r = app_client.get("/api/physique/distribution")
    assert r.status_code == 200
    data = r.json()
    assert "evaluable" in data
    keys = {m["key"] for m in data["metrics"]}
    assert keys == {"bmi", "body_fat", "ffmi", "vo2max"}
    for m in data["metrics"]:
        assert {
            "value", "mean", "sd", "percentile", "source", "target_low", "target_high", "label", "unit"
        } <= set(m)

def test_vo2max_falls_back_to_estimate(app_client, monkeypatch):
    """Garmin 実測が無い場合、metric_sample の推定値 (vo2max_estimated) で代替し出所を明示。"""
    from datetime import datetime

    from app.db import session_scope
    from app.models import MetricSample

    with session_scope() as s:
        s.add(MetricSample(source="estimate", metric_key="vo2max_estimated",
                           ts=datetime(2026, 7, 4, 12, 0, 5), value=48.9))

    r = app_client.get("/api/physique/distribution")
    assert r.status_code == 200
    vo2 = next(m for m in r.json()["metrics"] if m["key"] == "vo2max")
    assert vo2["value"] == 48.9
    assert vo2.get("estimated") is True


def test_as_of_body_comp_from_weight_sample(app_client):
    """体組成 (BMI/体脂肪/FFMI) の参照日時 = 最新 WeightSample.ts の app_tz 日付。"""
    from datetime import datetime

    from app.db import session_scope
    from app.models import WeightSample

    with session_scope() as s:
        # UTC 03:00 = JST 12:00 → 同日 2026-07-02
        s.add(WeightSample(ts=datetime(2026, 7, 2, 3, 0), weight_kg=65.0,
                           body_fat_pct=15.0, source="hae"))

    data = app_client.get("/api/physique/distribution").json()
    assert data["body_comp_as_of"] == "2026-07-02"
    assert data["vo2max_as_of"] is None


def test_as_of_vo2max_measured_from_daily_summary(app_client):
    from datetime import date

    from app.db import session_scope
    from app.models import DailySummary

    with session_scope() as s:
        s.add(DailySummary(date=date(2026, 7, 3), vo2max=49.0))

    data = app_client.get("/api/physique/distribution").json()
    assert data["vo2max_as_of"] == "2026-07-03"


def test_as_of_vo2max_estimated_from_metric_sample(app_client):
    from datetime import datetime

    from app.db import session_scope
    from app.models import MetricSample

    with session_scope() as s:
        s.add(MetricSample(source="estimate", metric_key="vo2max_estimated",
                           ts=datetime(2026, 7, 4, 12, 0, 5), value=48.9))

    data = app_client.get("/api/physique/distribution").json()
    assert data["vo2max_as_of"] == "2026-07-04"


def test_as_of_null_when_no_data(app_client):
    data = app_client.get("/api/physique/distribution").json()
    assert data["body_comp_as_of"] is None
    assert data["vo2max_as_of"] is None

