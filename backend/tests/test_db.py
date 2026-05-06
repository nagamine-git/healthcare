from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import (
    BodyBatteryDaily,
    DailyScore,
    HrvDaily,
    LlmComment,
    MetricSample,
    SleepSession,
    SourceSync,
    WeightSample,
    Workout,
)


def test_create_all_creates_tables(db_engine):
    from sqlalchemy import inspect

    inspector = inspect(db_engine)
    tables = set(inspector.get_table_names())
    assert {
        "metric_sample",
        "sleep_session",
        "hrv_daily",
        "body_battery",
        "body_battery_daily",
        "workout",
        "weight_sample",
        "daily_summary",
        "daily_score",
        "llm_comment",
        "source_sync",
    }.issubset(tables)


def test_metric_sample_unique_constraint(session):
    ts = datetime(2026, 5, 1, 7, 0, 0, tzinfo=UTC)
    session.add(MetricSample(source="garmin", metric_key="steps", ts=ts, value=100, unit="count"))
    session.commit()

    session.add(MetricSample(source="garmin", metric_key="steps", ts=ts, value=200, unit="count"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_sleep_session_primary_key_is_date(session):
    d = date(2026, 5, 1)
    session.add(SleepSession(date=d, source="garmin", total_min=420, sleep_score=82.0))
    session.commit()

    fetched = session.execute(select(SleepSession).where(SleepSession.date == d)).scalar_one()
    assert fetched.total_min == 420
    assert fetched.sleep_score == 82.0


def test_hrv_daily_can_persist_nullable_fields(session):
    session.add(HrvDaily(date=date(2026, 5, 1), last_night_avg=58.0))
    session.commit()
    fetched = session.execute(select(HrvDaily)).scalar_one()
    assert fetched.last_night_avg == 58.0
    assert fetched.weekly_avg is None


def test_weight_sample_persists(session):
    ts = datetime(2026, 5, 1, 6, 30, tzinfo=UTC)
    session.add(
        WeightSample(
            ts=ts, weight_kg=70.2, body_fat_pct=18.4, muscle_kg=33.0, source="hae"
        )
    )
    session.commit()
    row = session.execute(select(WeightSample)).scalar_one()
    assert row.weight_kg == 70.2
    assert row.body_fat_pct == 18.4


def test_workout_uses_string_id(session):
    session.add(
        Workout(
            id="garmin-12345",
            source="garmin",
            start=datetime(2026, 5, 1, 6, 0, tzinfo=UTC),
            end=datetime(2026, 5, 1, 7, 0, tzinfo=UTC),
            type="running",
            duration_s=3600,
            distance_m=10000,
            kcal=600,
            training_load=120,
            avg_hr=145,
            max_hr=170,
        )
    )
    session.commit()
    row = session.execute(select(Workout)).scalar_one()
    assert row.id == "garmin-12345"
    assert row.training_load == 120


def test_daily_score_round_trip(session):
    session.add(
        DailyScore(
            date=date(2026, 5, 1),
            sleep_sub=80.0,
            hrv_sub=70.0,
            bb_sub=85.0,
            load_sub=75.0,
            weight_sub=80.0,
            total=78.5,
            version="v1",
            computed_at=datetime(2026, 5, 1, 6, 30, tzinfo=UTC),
        )
    )
    session.commit()
    row = session.execute(select(DailyScore)).scalar_one()
    assert row.total == 78.5
    assert row.version == "v1"


def test_llm_comment_supports_multiple_per_day(session):
    d = date(2026, 5, 1)
    session.add(
        LlmComment(
            date=d,
            generated_at=datetime(2026, 5, 1, 6, 30, tzinfo=UTC),
            model="claude-haiku-4-5",
            prompt_hash="abc",
            comment="Good morning.",
        )
    )
    session.add(
        LlmComment(
            date=d,
            generated_at=datetime(2026, 5, 1, 18, 0, tzinfo=UTC),
            model="claude-haiku-4-5",
            prompt_hash="def",
            comment="Recovery looks solid.",
        )
    )
    session.commit()
    rows = session.execute(select(LlmComment)).scalars().all()
    assert len(rows) == 2


def test_source_sync_upsert_pattern(session):
    session.add(
        SourceSync(
            source="garmin",
            last_synced_at=datetime(2026, 5, 1, 6, 30, tzinfo=UTC),
            cursor_json={"date": "2026-05-01"},
        )
    )
    session.commit()
    row = session.get(SourceSync, "garmin")
    assert row is not None
    assert row.cursor_json == {"date": "2026-05-01"}


def test_body_battery_daily(session):
    session.add(
        BodyBatteryDaily(
            date=date(2026, 5, 1),
            max_value=92.0,
            min_value=20.0,
            end_of_day=45.0,
            morning_value=88.0,
        )
    )
    session.commit()
    row = session.execute(select(BodyBatteryDaily)).scalar_one()
    assert row.morning_value == 88.0
