"""「昨夜の睡眠」のトレンド系列が、欠測夜を位置ごと保って返すことの回帰テスト。

計測できた夜だけを詰めて返すと、1週間空いた夜が隣同士に描かれ「毎晩測れているのに
急変した」ように見えてしまう。日付の位置は必ず保つ。
"""

from __future__ import annotations

from datetime import date, timedelta

from app.api.sleep_quality import _history
from app.models import SleepSession


def test_missing_nights_keep_their_slot(db_engine, session):
    target = date(2026, 7, 24)
    # 10日窓に、7日離れた2夜だけデータを置く
    for d, total in ((target - timedelta(days=9), 400), (target - timedelta(days=2), 300)):
        session.add(SleepSession(
            date=d, source="garmin", total_min=total, deep_min=60, rem_min=80, awake_min=10))
    session.commit()

    h = _history(target, days=10)

    assert len(h) == 10, "窓の日数ぶん必ず返す (詰めない)"
    assert [x["date"] for x in h] == [
        (target - timedelta(days=i)).isoformat() for i in range(9, -1, -1)
    ], "日付は連続・昇順"
    measured = [i for i, x in enumerate(h) if x["total"] is not None]
    assert measured == [0, 7], "計測夜が元の間隔 (7日離れ) を保っている"
    # 欠測夜は 0 ではなく None (0 だと「まったく眠れなかった夜」の嘘グラフになる)
    assert h[3]["total"] is None
    assert h[3]["deep"] is None


def test_falls_back_to_previous_night_before_sync(db_engine, session, monkeypatch):
    """今日ぶんが未同期でも、直前の夜を出す (パネルごと消さない)。

    深夜0時台〜起床後の Garmin 同期までは今日の SleepSession が存在しない。
    そこで available:false を返すと、毎晩その時間帯だけパネルとトレンドが丸ごと消える。
    """
    import app.api.sleep_quality as api

    today = date(2026, 7, 24)
    session.add(SleepSession(
        date=today - timedelta(days=1), source="garmin",
        total_min=380, deep_min=60, rem_min=80, awake_min=10, sleep_score=70))
    session.commit()
    monkeypatch.setattr(api, "app_today", lambda: today)

    out = api.get_last_night()

    assert out["available"] is True
    assert out["date"] == (today - timedelta(days=1)).isoformat()
    assert out["is_previous_night"] is True, "「昨夜」と偽らず、前夜だと明示すること"
    assert len(out["history"]) == 30


def test_history_is_returned_even_when_unavailable(db_engine, session, monkeypatch):
    """評価が出せない日でもトレンドは返す (推移は昨夜のデータに依存しない)。"""
    import app.api.sleep_quality as api

    today = date(2026, 7, 24)
    monkeypatch.setattr(api, "app_today", lambda: today)

    out = api.get_last_night()

    assert out["available"] is False
    assert len(out["history"]) == 30
