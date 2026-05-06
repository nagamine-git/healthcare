from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import select

from app.ingest.garmin_client import (
    GarminClient,
    _normalise_body_battery,
    _normalise_sleep,
    _normalise_summary,
    _normalise_workout,
)
from app.ingest.garmin_sync import sync_garmin
from app.models import (
    BodyBattery,
    BodyBatteryDaily,
    DailySummary,
    HrvDaily,
    SleepSession,
    SourceSync,
    Workout,
)

SAMPLE_SLEEP = {
    "dailySleepDTO": {
        "sleepTimeSeconds": 7 * 3600,
        "deepSleepSeconds": 1 * 3600,
        "remSleepSeconds": 1.5 * 3600,
        "lightSleepSeconds": 4 * 3600,
        "awakeSleepSeconds": 30 * 60,
        "sleepScores": {"overall": {"value": 84}},
    },
    "hrvSummary": {"lastNightAvg": 62},
}


def test_normalise_sleep_extracts_minutes_and_score():
    n = _normalise_sleep(SAMPLE_SLEEP)
    assert n["total_min"] == 420
    assert n["deep_min"] == 60
    assert n["sleep_score"] == 84
    assert n["hrv_overnight_avg"] == 62


def test_normalise_body_battery_picks_morning_value():
    raw = [
        {
            "bodyBatteryValuesArray": [
                # entries: [epoch ms, status, value]
                [int(datetime(2026, 5, 1, 6, 0, tzinfo=UTC).timestamp() * 1000), "MEASURED", 88],
                [int(datetime(2026, 5, 1, 12, 0, tzinfo=UTC).timestamp() * 1000), "MEASURED", 60],
                [int(datetime(2026, 5, 1, 22, 0, tzinfo=UTC).timestamp() * 1000), "MEASURED", 30],
            ]
        }
    ]
    n = _normalise_body_battery(raw)
    assert len(n["series"]) == 3
    assert n["max"] == 88
    assert n["min"] == 30
    assert n["morning"] == 88


def test_normalise_workout_extracts_fields():
    activity = {
        "activityId": 12345,
        "activityType": {"typeKey": "running"},
        "startTimeGMT": "2026-05-01T05:00:00.0",
        "duration": 1800,
        "distance": 5000.0,
        "calories": 300,
        "averageHR": 140,
        "maxHR": 168,
        "activityTrainingLoad": 70,
    }
    n = _normalise_workout(activity)
    assert n["id"] == 12345
    assert n["duration_s"] == 1800
    assert n["distance_m"] == 5000.0
    assert n["type"] == "running"


def test_normalise_summary():
    n = _normalise_summary(
        {
            "totalSteps": 9876,
            "activeKilocalories": 540,
            "restingHeartRate": 52,
            "vo2Max": 48.5,
            "trainingStatus": "PRODUCTIVE",
        }
    )
    assert n["steps"] == 9876
    assert n["resting_hr"] == 52


# --- end-to-end sync via fake API client -----------------------------------


class FakeGarminAPI:
    def __init__(self) -> None:
        self.logged_in = False

    def login(self, tokenstore: str | None = None, tokenstore_base64: str | None = None):
        self.logged_in = True

    def get_sleep_data(self, cdate: str):
        return SAMPLE_SLEEP

    def get_hrv_data(self, cdate: str):
        return {
            "hrvSummary": {
                "lastNightAvg": 62,
                "weeklyAvg": 60,
                "status": "BALANCED",
                "baseline": {"lowUpper": 55, "balancedHigh": 70},
            }
        }

    def get_body_battery(self, startdate: str, enddate: str | None = None):
        return [
            {
                "bodyBatteryValuesArray": [
                    [
                        int(datetime(2026, 5, 1, 6, 0, tzinfo=UTC).timestamp() * 1000),
                        "MEASURED",
                        90,
                    ],
                    [
                        int(datetime(2026, 5, 1, 22, 0, tzinfo=UTC).timestamp() * 1000),
                        "MEASURED",
                        20,
                    ],
                ]
            }
        ]

    def get_activities_by_date(self, startdate: str, enddate: str):
        return [
            {
                "activityId": 999,
                "activityType": {"typeKey": "running"},
                "startTimeGMT": "2026-05-01T05:00:00.0",
                "duration": 1800,
                "distance": 5000.0,
                "calories": 300,
                "averageHR": 140,
                "maxHR": 168,
                "activityTrainingLoad": 70,
            }
        ]

    def get_user_summary(self, cdate: str):
        return {
            "totalSteps": 9876,
            "activeKilocalories": 540,
            "restingHeartRate": 52,
            "vo2Max": 48.5,
            "trainingStatus": "PRODUCTIVE",
        }

    def get_stress_data(self, cdate: str):
        return {
            "stressValuesArray": [
                [int(datetime(2026, 5, 1, 6, 0, tzinfo=UTC).timestamp() * 1000), 30],
                [int(datetime(2026, 5, 1, 12, 0, tzinfo=UTC).timestamp() * 1000), 55],
            ]
        }


def test_sync_garmin_persists_all_categories(db_engine, session):
    api = FakeGarminAPI()
    client = GarminClient(api)
    target = date(2026, 5, 1)

    result = sync_garmin(client, target=target)
    assert result["error"] is None
    assert result["counts"]["sleep"] == 1
    assert result["counts"]["hrv"] == 1
    assert result["counts"]["workouts"] == 1

    # Re-open a fresh session to verify
    sleep_row = session.get(SleepSession, target)
    assert sleep_row is not None
    assert sleep_row.sleep_score == 84

    hrv_row = session.get(HrvDaily, target)
    assert hrv_row is not None
    assert hrv_row.last_night_avg == 62

    bb_row = session.get(BodyBatteryDaily, target)
    assert bb_row is not None
    assert bb_row.morning_value == 90

    workout = session.get(Workout, "garmin-999")
    assert workout is not None
    assert workout.duration_s == 1800

    summary = session.get(DailySummary, target)
    assert summary is not None
    assert summary.steps == 9876

    sync_status = session.get(SourceSync, "garmin")
    assert sync_status is not None
    assert sync_status.last_synced_at is not None
    assert sync_status.last_error is None


def test_sync_garmin_records_error_when_login_fails(db_engine, session):
    class FailingAPI(FakeGarminAPI):
        def login(self, **_):
            raise RuntimeError("429 too many requests")

    client = GarminClient(FailingAPI())
    target = date(2026, 5, 1)
    result = sync_garmin(client, target=target)
    assert result["error"] is not None
    sync_status = session.get(SourceSync, "garmin")
    assert sync_status is not None
    assert "429" in (sync_status.last_error or "")


def test_garmin_body_battery_series_persisted_to_metric_sample(db_engine, session):
    api = FakeGarminAPI()
    client = GarminClient(api)
    sync_garmin(client, target=date(2026, 5, 1))

    # body_battery time-series should be persisted to BodyBattery table
    rows = select(BodyBattery)
    rows = session.execute(rows).scalars().all()
    assert len(rows) == 2


def test_sync_garmin_job_skips_when_no_token(temp_data_dir, monkeypatch):
    """credential login で Garmin に 429 を踏まないため、トークン未取得時は skip."""
    import asyncio

    monkeypatch.setenv("APP_DATA_DIR", str(temp_data_dir))
    monkeypatch.setenv("GARMIN_EMAIL", "x@example.com")
    monkeypatch.setenv("GARMIN_PASSWORD", "x")
    from app.config import reset_settings_cache

    reset_settings_cache()

    from app.ingest.garmin_sync import sync_garmin_job

    result = asyncio.run(sync_garmin_job())
    assert result["status"] == "skipped"
    assert result["reason"] == "no_token"


def test_sync_garmin_job_skips_when_no_credentials(temp_data_dir, monkeypatch):
    import asyncio

    monkeypatch.setenv("APP_DATA_DIR", str(temp_data_dir))
    monkeypatch.delenv("GARMIN_EMAIL", raising=False)
    monkeypatch.delenv("GARMIN_PASSWORD", raising=False)
    from app.config import reset_settings_cache

    reset_settings_cache()

    from app.ingest.garmin_sync import sync_garmin_job

    result = asyncio.run(sync_garmin_job())
    assert result["status"] == "skipped"
    assert result["reason"] == "no_credentials"


def test_sync_garmin_job_runs_when_token_present(temp_data_dir, monkeypatch):
    import asyncio

    token_dir = temp_data_dir / "garmin_tokens"
    token_dir.mkdir()
    (token_dir / "garmin_tokens.json").write_text("{}")

    monkeypatch.setenv("APP_DATA_DIR", str(temp_data_dir))
    monkeypatch.setenv("GARMIN_EMAIL", "x@example.com")
    monkeypatch.setenv("GARMIN_PASSWORD", "x")
    from app.config import reset_settings_cache

    reset_settings_cache()

    from app.db import create_all, init_engine

    init_engine(temp_data_dir / "test.sqlite3")
    create_all()

    # Patch the actual login to use a fake API so we don't hit Garmin
    from app.ingest import garmin_client as gc_module

    original = gc_module.GarminClient.from_settings

    def _fake_from_settings(settings):
        return gc_module.GarminClient(FakeGarminAPI())

    monkeypatch.setattr(gc_module.GarminClient, "from_settings", classmethod(lambda cls, s: gc_module.GarminClient(FakeGarminAPI())))

    from app.ingest.garmin_sync import sync_garmin_job

    result = asyncio.run(sync_garmin_job())
    assert result.get("status") != "skipped"
    assert "counts" in result

    monkeypatch.setattr(gc_module.GarminClient, "from_settings", original)
