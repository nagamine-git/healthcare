from __future__ import annotations

from datetime import datetime, timedelta

from app.db import session_scope
from app.models import MetricSample
from app.scoring import habit_pace as hp


def _water(s, ts, ml):
    s.add(MetricSample(source="garmin", metric_key="garmin_hydration_ml", ts=ts, value=float(ml)))


def test_behind_pace_triggers_nudge(db_engine):
    # 今 JST 14:00。過去14日は毎日 09:00 に 800ml 飲んでいた → 今頃は 800ml が普通。
    now = datetime(2026, 6, 15, 14, 0)
    for i in range(1, 15):
        d = now.date() - timedelta(days=i)
        ts_utc = datetime(d.year, d.month, d.day, 0, 0)  # JST 09:00 = UTC 00:00
        with session_scope() as s:
            _water(s, ts_utc, 800)
    # 今日は飲んでいない
    out = hp.state(now_jst=now)
    water = next(h for h in out["habits"] if h["key"] == "water")
    assert water["expected"] == 800
    assert water["actual"] == 0
    assert water["status"] == "behind"
    assert water["nudge"] is not None and "飲もう" in water["nudge"]
    assert any("水" in n or "💧" in n for n in out["nudges"])


def test_on_pace_no_nudge(db_engine):
    now = datetime(2026, 6, 15, 14, 0)
    for i in range(1, 15):
        d = now.date() - timedelta(days=i)
        with session_scope() as s:
            _water(s, datetime(d.year, d.month, d.day, 0, 0), 800)
    # 今日も 800ml 飲んでいる (JST 10:00 = UTC 01:00、cutoff 14:00 以内)
    with session_scope() as s:
        _water(s, datetime(now.year, now.month, now.day, 1, 0), 800)
    out = hp.state(now_jst=now)
    water = next(h for h in out["habits"] if h["key"] == "water")
    assert water["status"] == "on_pace"
    assert water["nudge"] is None


def test_insufficient_history_no_judgement(db_engine):
    now = datetime(2026, 6, 15, 14, 0)
    # 履歴2日だけ → _MIN_DAYS 未満で no_data
    for i in (1, 2):
        d = now.date() - timedelta(days=i)
        with session_scope() as s:
            _water(s, datetime(d.year, d.month, d.day, 0, 0), 800)
    out = hp.state(now_jst=now)
    water = next(h for h in out["habits"] if h["key"] == "water")
    assert water["status"] == "no_data"
