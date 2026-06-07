from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import select

from app.db import session_scope
from app.models import MetricSample, SleepSession


def _local_ms(y: int, m: int, d: int, hh: int, mm: int) -> int:
    """Garmin の *TimestampLocal (ローカル壁時計を epoch ms にしたもの) を作る。"""
    return int(datetime(y, m, d, hh, mm, tzinfo=UTC).timestamp() * 1000)


SAMPLE_RAW = {
    "dailySleepDTO": {
        "averageSpO2Value": 93.0,
        "lowestSpO2Value": 72,
        "averageRespirationValue": 13.0,
        "avgSleepStress": 14.0,
        "napTimeSeconds": 1200,
        "breathingDisruptionSeverity": "LOW",
        "sleepStartTimestampLocal": _local_ms(2026, 6, 5, 23, 30),
        "sleepEndTimestampLocal": _local_ms(2026, 6, 6, 7, 0),
    },
    "restingHeartRate": 46,
    "restlessMomentsCount": 38,
    "bodyBatteryChange": 73,
}


def test_extract_sleep_extras_full():
    from app.ingest.sleep_extras import extract_sleep_extras

    m = extract_sleep_extras(SAMPLE_RAW)
    assert m["sleep_spo2_avg"] == 93.0
    assert m["sleep_spo2_lowest"] == 72.0
    assert m["sleep_respiration_avg"] == 13.0
    assert m["sleep_stress_avg"] == 14.0
    assert m["sleep_resting_hr"] == 46.0
    assert m["sleep_restless_moments"] == 38.0
    assert m["sleep_bb_change"] == 73.0
    assert m["sleep_nap_min"] == 20.0
    assert m["sleep_breath_disruption"] == 0.0  # LOW
    # 23:30 就寝 → 07:00 起床 の中点は 03:15 = 3.25 時
    assert abs(m["sleep_midpoint_hour"] - 3.25) < 0.01


def test_extract_sleep_extras_skips_missing():
    from app.ingest.sleep_extras import extract_sleep_extras

    m = extract_sleep_extras({"dailySleepDTO": {"averageSpO2Value": None}})
    assert m == {}


def test_store_and_backfill(db_engine):
    from app.ingest.sleep_extras import backfill_sleep_extras

    target = date(2026, 6, 6)
    with session_scope() as s:
        s.add(SleepSession(date=target, source="garmin", total_min=450, raw_json=SAMPLE_RAW))
        # raw_json なしの行はスキップされる
        s.add(SleepSession(date=date(2026, 6, 5), source="garmin", total_min=400))

    n = backfill_sleep_extras()
    assert n == 1  # 1 日分処理

    with session_scope() as s:
        rows = s.execute(
            select(MetricSample.metric_key, MetricSample.value).where(
                MetricSample.metric_key.like("sleep_%"))
        ).all()
        by_key = {r[0]: r[1] for r in rows}
    assert by_key["sleep_spo2_lowest"] == 72.0
    assert abs(by_key["sleep_midpoint_hour"] - 3.25) < 0.01

    # 再実行しても重複しない (upsert)
    backfill_sleep_extras()
    with session_scope() as s:
        cnt = s.execute(
            select(MetricSample.metric_key).where(MetricSample.metric_key == "sleep_spo2_avg")
        ).all()
    assert len(cnt) == 1
