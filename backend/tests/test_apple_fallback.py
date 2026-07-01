from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import select

from app.db import session_scope
from app.ingest.apple_fallback import APPLE_HRV_KEY, apply_apple_sleep_fallback
from app.models import MetricSample

TARGET = date(2026, 7, 1)
# 夜次マーカー ts(store_sleep_extras と同じ)
NIGHT_TS = datetime.combine(TARGET, time(7, 0))


def _add(session, source, key, ts, value):
    session.add(MetricSample(source=source, metric_key=key, ts=ts, value=value))


def _get(session, source, key, ts=NIGHT_TS):
    """該当 (source, key, ts) の value を返す(無ければ None)。"""
    row = session.execute(
        select(MetricSample.value).where(
            MetricSample.source == source, MetricSample.metric_key == key, MetricSample.ts == ts
        )
    ).first()
    return row[0] if row else None


def test_spo2_fallback_when_garmin_absent(db_engine):
    # JST 7/1 の夜 = UTC 6/30 14:00〜16:00 は窓内([6/30 11:00, 7/1 02:00))
    with session_scope() as s:
        _add(s, "hae", "blood_oxygen_saturation", datetime(2026, 6, 30, 14, 0), 96)
        _add(s, "hae", "blood_oxygen_saturation", datetime(2026, 6, 30, 15, 0), 92)
        _add(s, "hae", "blood_oxygen_saturation", datetime(2026, 6, 30, 16, 0), 85)
    with session_scope() as s:
        out = apply_apple_sleep_fallback(s, TARGET)
    assert out["spo2_lowest"] == 85.0 and round(out["spo2_avg"]) == 91
    with session_scope() as s:
        assert _get(s, "hae", "sleep_spo2_avg") is not None
        assert _get(s, "hae", "sleep_spo2_lowest") == 85.0


def test_garmin_spo2_present_removes_fallback(db_engine):
    with session_scope() as s:
        _add(s, "hae", "blood_oxygen_saturation", datetime(2026, 6, 30, 15, 0), 90)
        _add(s, "hae", "sleep_spo2_avg", NIGHT_TS, 90)  # 以前のフォールバック
        _add(s, "garmin", "sleep_spo2_avg", NIGHT_TS, 97)  # Garmin が本データを取得
    with session_scope() as s:
        apply_apple_sleep_fallback(s, TARGET)
    with session_scope() as s:
        # Garmin 優先。hae フォールバックは撤去(重複カウント防止)。
        assert _get(s, "hae", "sleep_spo2_avg") is None
        assert _get(s, "garmin", "sleep_spo2_avg") == 97


def test_hrv_stored_as_reference_not_in_hrv_daily(db_engine):
    from app.models import HrvDaily

    with session_scope() as s:
        _add(s, "hae", "heart_rate_variability", datetime(2026, 6, 30, 15, 0), 40)
        _add(s, "hae", "heart_rate_variability", datetime(2026, 6, 30, 16, 0), 44)
    with session_scope() as s:
        out = apply_apple_sleep_fallback(s, TARGET)
    assert out["hrv_sdnn"] == 42.0
    with session_scope() as s:
        assert _get(s, "hae", APPLE_HRV_KEY) == 42.0
        # HRV baseline を汚さない: hrv_daily には一切書かない。
        assert s.get(HrvDaily, TARGET) is None
