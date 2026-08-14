"""歩数の唯一の入口 (resolve_steps) と JST 日窓。

過去に「AIアドバイス=Garmin単独」「habit_pace=HAE単独」「/api/activity だけ合流」と
3つの定義が並立し、実測 14,043 歩の日に助言は 195 歩を前提に作られていた。
さらに集計窓が UTC 日付だったため 9 時間ずれ、同じ日が 14,043 / 5,061 と別物になった。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from app.models import DailySummary, MetricSample
from app.scoring.activity_signal import _jst_day_bounds, resolve_steps

DAY = date(2026, 8, 4)


def _hae(session, *, jst_hour: int, value: float, day: date = DAY) -> None:
    """JST の指定時刻に HAE の歩数サンプルを置く (DB は UTC naive 保存)。"""
    ts = datetime.combine(day, datetime.min.time()) + timedelta(hours=jst_hour - 9)
    session.add(MetricSample(source="hae", metric_key="step_count", ts=ts, value=value))


def test_jst_window_covers_the_whole_local_day(db_engine, session):
    """JST 00:10 の歩数が「その日」に入る。⚠️ UTC 日付で束ねると前日に落ちる。"""
    _hae(session, jst_hour=0, value=1000)    # JST 00:00台 = UTC 前日 15:00台
    _hae(session, jst_hour=23, value=2000)   # JST 23:00台
    session.commit()

    assert resolve_steps(session, DAY) == 3000


def test_next_day_early_morning_does_not_leak_in(db_engine, session):
    """翌日の朝の歩数が混入しない (UTC 窓だと混ざっていた)。"""
    _hae(session, jst_hour=8, value=500, day=DAY + timedelta(days=1))
    session.commit()

    assert resolve_steps(session, DAY) is None


def test_takes_max_not_sum(db_engine, session):
    """同じ歩行を2ソースが別々に数えるので**合算しない**。取りこぼす方向にしか外れない。"""
    session.add(DailySummary(date=DAY, steps=195))
    _hae(session, jst_hour=12, value=14043)
    session.commit()

    assert resolve_steps(session, DAY) == 14043, "小さい方 (Garmin未同期) に引っ張られない"


def test_falls_back_to_the_only_available_source(db_engine, session):
    session.add(DailySummary(date=DAY, steps=8000))
    session.commit()
    assert resolve_steps(session, DAY) == 8000

    assert resolve_steps(session, DAY + timedelta(days=3)) is None


def test_bounds_are_utc_naive_and_span_24h():
    lo, hi = _jst_day_bounds(DAY)
    assert (hi - lo) == timedelta(days=1)
    assert lo == datetime(2026, 8, 3, 15, 0), "JST 00:00 = UTC 前日 15:00"
