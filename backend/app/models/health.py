from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class MetricSample(Base):
    """Long-format time-series for fine-grained metrics."""

    __tablename__ = "metric_sample"
    __table_args__ = (UniqueConstraint("source", "metric_key", "ts", name="uq_metric_sample"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32), index=True)  # garmin | hae
    metric_key: Mapped[str] = mapped_column(String(64), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, index=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    raw_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class SleepSession(Base):
    __tablename__ = "sleep_session"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    total_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deep_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rem_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    light_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    awake_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sleep_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    hrv_overnight_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class HrvDaily(Base):
    __tablename__ = "hrv_daily"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    last_night_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    weekly_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    baseline_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    baseline_high: Mapped[float | None] = mapped_column(Float, nullable=True)


class BodyBattery(Base):
    __tablename__ = "body_battery"

    ts: Mapped[datetime] = mapped_column(DateTime, primary_key=True)
    value: Mapped[float] = mapped_column(Float)
    charged: Mapped[float | None] = mapped_column(Float, nullable=True)
    drained: Mapped[float | None] = mapped_column(Float, nullable=True)


class BodyBatteryDaily(Base):
    __tablename__ = "body_battery_daily"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    max_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_of_day: Mapped[float | None] = mapped_column(Float, nullable=True)
    morning_value: Mapped[float | None] = mapped_column(Float, nullable=True)


class Workout(Base):
    __tablename__ = "workout"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    start: Mapped[datetime] = mapped_column(DateTime, index=True)
    end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    kcal: Mapped[float | None] = mapped_column(Float, nullable=True)
    training_load: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class WeightSample(Base):
    __tablename__ = "weight_sample"

    ts: Mapped[datetime] = mapped_column(DateTime, primary_key=True)
    weight_kg: Mapped[float] = mapped_column(Float)
    body_fat_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    muscle_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    water_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(32))


class DailySummary(Base):
    __tablename__ = "daily_summary"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    steps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active_kcal: Mapped[float | None] = mapped_column(Float, nullable=True)
    resting_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    vo2max: Mapped[float | None] = mapped_column(Float, nullable=True)
    training_status: Mapped[str | None] = mapped_column(String(32), nullable=True)


class DailyScore(Base):
    __tablename__ = "daily_score"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    sleep_sub: Mapped[float | None] = mapped_column(Float, nullable=True)
    hrv_sub: Mapped[float | None] = mapped_column(Float, nullable=True)
    bb_sub: Mapped[float | None] = mapped_column(Float, nullable=True)
    load_sub: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight_sub: Mapped[float | None] = mapped_column(Float, nullable=True)
    body_fat_sub: Mapped[float | None] = mapped_column(Float, nullable=True)
    total: Mapped[float | None] = mapped_column(Float, nullable=True)
    version: Mapped[str] = mapped_column(String(16))
    computed_at: Mapped[datetime] = mapped_column(DateTime)


class LlmComment(Base):
    __tablename__ = "llm_comment"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, primary_key=True)
    model: Mapped[str] = mapped_column(String(64))
    prompt_hash: Mapped[str] = mapped_column(String(64))
    comment: Mapped[str] = mapped_column(String(2000))


class SourceSync(Base):
    __tablename__ = "source_sync"

    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    cursor_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


# Foreign keys not strictly needed for SQLite single-user, kept simple intentionally.
_ = ForeignKey  # silence unused import if not referenced elsewhere
