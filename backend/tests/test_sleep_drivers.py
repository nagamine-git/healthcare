from __future__ import annotations

from datetime import date, datetime, timedelta

from app.db import session_scope
from app.models import AlcoholIntake, SleepSession
from app.scoring import sleep_drivers as sd


def test_accumulating_below_min(db_engine):
    today = date(2026, 6, 15)
    with session_scope() as s:
        for i in range(3):
            d = today - timedelta(days=i)
            s.add(SleepSession(date=d, source="garmin", total_min=420, awake_min=30, sleep_score=70))
    out = sd.analyze(today)
    assert out["status"] == "accumulating"
    assert out["n_nights"] == 3


def test_alcohol_lowers_efficiency(db_engine):
    """夜に飲酒した夜は睡眠効率が低い → alcohol_eve が悪化方向で出る。"""
    today = date(2026, 6, 15)
    with session_scope() as s:
        for i in range(1, 41):
            d = today - timedelta(days=i)
            drank = i % 2 == 0
            # 飲酒夜は効率85、非飲酒夜は効率95 (awake_min で差をつける)
            awake = 75 if drank else 22
            s.add(SleepSession(date=d, source="garmin", total_min=420, awake_min=awake, sleep_score=70))
            if drank:
                # 前日(d-1)の夜 20:00 に飲酒
                ts = datetime.combine(d - timedelta(days=1), datetime.min.time()).replace(hour=11)  # JST20:00=UTC11:00
                s.add(AlcoholIntake(ts=ts, source="beer", grams=20.0))
    out = sd.analyze(today)
    assert out["status"] == "analyzed"
    alc = next((f for f in out["quality"] if f["driver"] == "alcohol_eve" and f["outcome"] == "efficiency"), None)
    assert alc is not None, out["quality"]
    assert alc["direction"] == "悪化"
    assert alc["tier"] in ("strong", "suggestive", "trend")


def test_preliminary_signal_below_gate(db_engine):
    """8夜未満 (ゲート未達) でも各群>=2あれば暫定シグナル (方向+効果量) を出す。"""
    today = date(2026, 6, 15)
    with session_scope() as s:
        for i in range(1, 6):  # 5夜
            d = today - timedelta(days=i)
            drank = i % 2 == 0  # i=2,4 の 2 夜
            awake = 75 if drank else 22
            s.add(SleepSession(date=d, source="garmin", total_min=420, awake_min=awake, sleep_score=70))
            if drank:
                ts = datetime.combine(d - timedelta(days=1), datetime.min.time()).replace(hour=11)
                s.add(AlcoholIntake(ts=ts, source="beer", grams=20.0))
    out = sd.analyze(today)
    assert out["status"] == "preliminary"
    alc = next(
        (f for f in out["quality"] if f["driver"] == "alcohol_eve" and f["outcome"] == "efficiency"),
        None,
    )
    assert alc is not None, out
    assert alc["tier"] == "preliminary"
    assert alc["direction"] == "悪化"
