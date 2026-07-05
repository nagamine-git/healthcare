"""筋トレ頻度カウント (_strength_days_in_window) の共有ヘルパ テスト。"""

from __future__ import annotations

from datetime import date, datetime, timedelta


def _add(session, days_ago: int, wtype: str, hour: int = 12):
    from app.models import Workout

    start = datetime(2026, 7, 5, hour) - timedelta(days=days_ago)
    session.add(Workout(id=f"w{days_ago}-{wtype}-{hour}", source="garmin", start=start,
                        end=start + timedelta(minutes=40), type=wtype, duration_s=2400))


def test_counts_distinct_strength_days_in_window(db_engine, session):
    from app.llm.client import _strength_days_in_window

    # 直近14日に strength 3日 (うち1日は2セッション=1日カウント) + running は除外
    _add(session, 1, "strength_training")
    _add(session, 3, "strength_training", hour=8)
    _add(session, 3, "strength_training", hour=18)  # 同日2回 → 1
    _add(session, 6, "weight_training")
    _add(session, 2, "running")                     # 除外
    _add(session, 20, "strength_training")           # 窓外 (14日超)
    session.commit()

    assert _strength_days_in_window(date(2026, 7, 5), days=14) == 3


def test_zero_when_no_strength(db_engine, session):
    from app.llm.client import _strength_days_in_window

    _add(session, 1, "running")
    session.commit()
    assert _strength_days_in_window(date(2026, 7, 5), days=14) == 0
