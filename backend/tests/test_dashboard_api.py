from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.models import (
    BodyBatteryDaily,
    DailyScore,
    DailySummary,
    HrvDaily,
    LlmComment,
    SleepSession,
    SourceSync,
    WeightSample,
)


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


def _seed_today(session, today: date) -> None:
    session.add(
        SleepSession(
            date=today,
            source="garmin",
            total_min=420,
            deep_min=80,
            rem_min=90,
            light_min=240,
            awake_min=10,
            sleep_score=85,
        )
    )
    session.add(HrvDaily(date=today, last_night_avg=62, weekly_avg=60, status="BALANCED"))
    session.add(
        BodyBatteryDaily(
            date=today, max_value=92, min_value=20, end_of_day=45, morning_value=88
        )
    )
    session.add(DailySummary(date=today, steps=12000, active_kcal=480, resting_hr=52))
    session.add(
        DailyScore(
            date=today,
            sleep_sub=85,
            hrv_sub=70,
            bb_sub=88,
            load_sub=85,
            weight_sub=80,
            total=82.0,
            version="v1",
            computed_at=datetime.now(UTC).replace(tzinfo=None),
        )
    )
    session.add(
        WeightSample(
            ts=datetime.combine(today, datetime.min.time()),
            weight_kg=70.5,
            body_fat_pct=18.0,
            source="hae",
        )
    )
    session.add(
        LlmComment(
            date=today,
            generated_at=datetime.now(UTC).replace(tzinfo=None),
            model="claude-haiku-4-5",
            prompt_hash="abc",
            comment="本日は安定したコンディション。根拠: 総合スコア 82。",
        )
    )
    session.add(
        SourceSync(
            source="garmin",
            last_synced_at=datetime.now(UTC).replace(tzinfo=None),
        )
    )


def test_today_returns_full_payload(app_client):
    from app.db import session_scope

    today = date.today()
    with session_scope() as session:
        _seed_today(session, today)

    resp = app_client.get("/api/today")
    assert resp.status_code == 200
    body = resp.json()

    assert body["date"] == today.isoformat()
    assert body["score"]["total"] == 82.0
    assert body["score"]["sleep"] == 85
    assert body["metrics"]["sleep"]["total_min"] == 420
    assert body["metrics"]["body_battery"]["morning"] == 88
    assert body["metrics"]["weight"]["weight_kg"] == 70.5
    assert body["advice"]["comment"].startswith("本日")
    assert "garmin" in body["sync"]


def test_timeseries_score(app_client):
    from app.db import session_scope

    today = date.today()
    with session_scope() as session:
        for i in range(7):
            d = today - timedelta(days=i)
            session.add(
                DailyScore(
                    date=d,
                    total=70 + i,
                    version="v1",
                    computed_at=datetime.now(UTC).replace(tzinfo=None),
                )
            )

    resp = app_client.get("/api/timeseries", params={"metric": "score", "days": 14})
    assert resp.status_code == 200
    body = resp.json()
    assert body["metric"] == "score"
    assert len(body["data"]) == 7
    # Should be in ascending order
    dates = [row["date"] for row in body["data"]]
    assert dates == sorted(dates)


def test_admin_recompute_writes_score(app_client):
    from app.db import session_scope

    today = date.today()
    with session_scope() as session:
        session.add(
            SleepSession(
                date=today,
                source="garmin",
                total_min=420,
                sleep_score=80,
            )
        )

    resp = app_client.post("/admin/recompute")
    assert resp.status_code == 200
    body = resp.json()
    assert body["date"] == today.isoformat()
    # Sleep is the only filled subscore, so total ≈ 80
    assert body["result"]["subs"]["sleep"] == 80
    assert body["result"]["total"] is not None

    with session_scope() as session:
        score = session.get(DailyScore, today)
        assert score is not None
        assert score.sleep_sub == 80


def test_timeseries_unknown_metric_returns_empty(app_client):
    resp = app_client.get("/api/timeseries", params={"metric": "totally-unknown"})
    assert resp.status_code == 200
    assert resp.json()["data"] == []


def test_trends_endpoint_daily(app_client):
    from app.db import session_scope

    today = date.today()
    with session_scope() as session:
        # 8 日分、total を単調増加で seed
        for i in range(8):
            d = today - timedelta(days=7 - i)
            session.add(
                DailyScore(
                    date=d,
                    total=60 + i * 2,
                    sleep_sub=70,
                    hrv_sub=65,
                    bb_sub=80,
                    load_sub=85,
                    weight_sub=75,
                    body_fat_sub=90,
                    version="v1",
                    computed_at=datetime.now(UTC).replace(tzinfo=None),
                )
            )

    resp = app_client.get("/api/trends", params={"granularity": "daily", "days": 28})
    assert resp.status_code == 200
    body = resp.json()
    assert body["granularity"] == "daily"
    total = body["metrics"]["total"]
    assert total["label"] == "総合スコア"
    assert total["current"] == 74
    assert total["prev_day_change"] == 2
    assert total["direction"] == "improving"
    assert total["higher_is_better"] is True
    assert len(total["series"]) == 8
    # 全指標キーが揃う
    assert set(body["metrics"].keys()) == {
        "total", "sleep", "hrv", "body_battery", "load", "weight", "body_fat",
    }


def test_trends_endpoint_weekly(app_client):
    from app.db import session_scope

    today = date.today()
    with session_scope() as session:
        for i in range(14):
            d = today - timedelta(days=13 - i)
            session.add(
                DailyScore(
                    date=d,
                    total=70.0,
                    version="v1",
                    computed_at=datetime.now(UTC).replace(tzinfo=None),
                )
            )

    resp = app_client.get("/api/trends", params={"granularity": "weekly", "days": 28})
    assert resp.status_code == 200
    body = resp.json()
    assert body["granularity"] == "weekly"
    # 週平均なので series 点数は日数より少ない (高々 3 週)
    assert len(body["metrics"]["total"]["series"]) <= 3
    assert all(p["value"] == 70.0 for p in body["metrics"]["total"]["series"])
