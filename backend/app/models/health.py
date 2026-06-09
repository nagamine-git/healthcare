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
    # 構造化版 (tool_use の input そのまま): {focus, actions: [...], rationale}
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class MigraineEpisode(Base):
    """偏頭痛エピソード。「痛くなった→治った」を 1 件として記録する。

    ended_at が None のものは active (現在進行中)。
    severity は 1-10 の主観強度 (省略可)。トリガー記録のため note を任意。
    """

    __tablename__ = "migraine_episode"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, index=True)  # UTC naive
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    severity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)


class AlcoholIntake(Base):
    """アルコール摂取の手動記録。

    grams は純アルコール量 (g)。これは飲料種類 × 量 × ABV × 0.8 で算出する。
    Pietilä 2018: 純アルコール 10g (約 1 drink) で深い睡眠 -20%、HRV -10〜15%。

    source 例: "beer" (中ジョッキ 350ml × 5% × 0.8 = 14g)、"wine"、"sake"、"shochu"、
    "highball"、"manual" (g 直接入力)。
    """

    __tablename__ = "alcohol_intake"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, index=True)
    source: Mapped[str] = mapped_column(String(32), index=True)
    amount_ml: Mapped[float | None] = mapped_column(Float, nullable=True)
    abv_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    grams: Mapped[float] = mapped_column(Float)  # 純アルコール g
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)


class CaffeineIntake(Base):
    """ユーザーが手動で記録したカフェイン摂取イベント。

    source は摂取源の分類 (instant_coffee / canned_coffee / nespresso / ibuquick / manual)。
    amount は元の量 (g, 本, 錠, mg) の数値、unit はその単位文字列。
    mg は **実際のカフェイン量** (推奨計算で使う、source から自動算出 or 手動入力)。
    """

    __tablename__ = "caffeine_intake"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, index=True)  # UTC naive
    source: Mapped[str] = mapped_column(String(32), index=True)
    amount: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(16))
    mg: Mapped[float] = mapped_column(Float)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)


class SourceSync(Base):
    __tablename__ = "source_sync"

    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    cursor_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class DomainWeight(Base):
    """ライフドメインの重み (ユーザーが調整。プリセット適用 or スライダー)。"""

    __tablename__ = "domain_weight"

    domain: Mapped[str] = mapped_column(String(32), primary_key=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0)


class UserProfile(Base):
    """UI から設定する個人プロファイルの上書き (単一行、id=1 固定)。

    値が NULL のフィールドは config.py (env) のデフォルトにフォールバックする。
    目標体型シルエットで設定した体重・体脂肪率を保持する。
    """

    __tablename__ = "user_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    height_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    sex: Mapped[str | None] = mapped_column(String(8), nullable=True)
    target_weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_body_fat_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    body_fat_tolerance_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    ffmi_normalized: Mapped[float | None] = mapped_column(Float, nullable=True)


class SubjectiveCheckin(Base):
    """日次の主観チェックイン (JST 日付ごと、1 日 1 行)。

    客観データ (HRV/睡眠 等) が代理する「実際どう感じるか」の結果変数。
    全項目 optional。mood/energy は高いほど良い、stress/soreness は高いほど悪い。
    """

    __tablename__ = "subjective_checkin"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    mood: Mapped[int | None] = mapped_column(Integer, nullable=True)
    energy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stress: Mapped[int | None] = mapped_column(Integer, nullable=True)
    soreness: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class SpeechSession(Base):
    """speech-coach から取り込む日次の発話練習サマリ (JST 日付ごと)。"""

    __tablename__ = "speech_session"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    session_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_overall: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_pace: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_pitch: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_clarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_filler: Mapped[float | None] = mapped_column(Float, nullable=True)


class ExternalDomainEntry(Base):
    """外部ライフドメイン (学習・仕事 等) の日次達成度を取り込む汎用テーブル。"""

    __tablename__ = "external_domain_entry"

    domain: Mapped[str] = mapped_column(String(32), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    achievement: Mapped[float | None] = mapped_column(Float, nullable=True)
    detail: Mapped[str | None] = mapped_column(String(200), nullable=True)


# Foreign keys not strictly needed for SQLite single-user, kept simple intentionally.
_ = ForeignKey  # silence unused import if not referenced elsewhere
