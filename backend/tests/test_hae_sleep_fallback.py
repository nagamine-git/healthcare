from __future__ import annotations

from datetime import date

from app.db import session_scope
from app.ingest.hae_parser import NormalizedSleep
from app.ingest.hae_writer import _write_sleeps
from app.models.health import SleepSession


def _apple_sleep(d: date) -> NormalizedSleep:
    return NormalizedSleep(
        date=d, source="hae", total_min=400, deep_min=90, rem_min=80,
        light_min=225, awake_min=5, sleep_score=None,
    )


def test_garmin_with_data_wins_over_apple(db_engine):
    d = date(2026, 7, 1)
    with session_scope() as s:
        s.add(SleepSession(date=d, source="garmin", total_min=349, deep_min=102,
                           rem_min=80, light_min=167, awake_min=5, sleep_score=75.0))
    with session_scope() as s:
        _write_sleeps(s, [_apple_sleep(d)])
    with session_scope() as s:
        row = s.get(SleepSession, d)
        assert row.source == "garmin" and row.total_min == 349  # Apple は上書きしない


def test_apple_fills_empty_garmin_row(db_engine):
    # Garmin を着けずに寝た夜 = Garmin 行はあるが total_min が None → Apple で補完。
    d = date(2026, 7, 1)
    with session_scope() as s:
        s.add(SleepSession(date=d, source="garmin", total_min=None))
    with session_scope() as s:
        _write_sleeps(s, [_apple_sleep(d)])
    with session_scope() as s:
        row = s.get(SleepSession, d)
        assert row.source == "hae" and row.total_min == 400 and row.deep_min == 90


def test_apple_creates_when_absent(db_engine):
    d = date(2026, 7, 1)
    with session_scope() as s:
        _write_sleeps(s, [_apple_sleep(d)])
    with session_scope() as s:
        row = s.get(SleepSession, d)
        assert row is not None and row.source == "hae" and row.total_min == 400


def test_empty_garmin_poll_does_not_clobber_apple(db_engine):
    # Apple 実データがある行を、Garmin の空ポーリング(total_min None)で潰さない。
    from app.ingest.garmin_sync import _upsert_sleep

    d = date(2026, 7, 1)
    with session_scope() as s:
        _write_sleeps(s, [_apple_sleep(d)])  # Apple が実データを書く
    with session_scope() as s:
        _upsert_sleep(s, d, {"total_min": None, "raw_json": None})  # Garmin 空ポール
    with session_scope() as s:
        row = s.get(SleepSession, d)
        assert row.source == "hae" and row.total_min == 400  # 温存される
