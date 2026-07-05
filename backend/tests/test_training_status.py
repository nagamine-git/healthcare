"""トレーニング状況 (build_status 純関数) のテスト。"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.scoring.training_status import build_status

NOW = datetime(2026, 7, 5, 15, 0)


def _sess(days_ago: int, ty: str):
    return {"date": (NOW - timedelta(days=days_ago)).date(), "type": ty}


def test_under_training_way_behind():
    # 直近7日に筋トレ1回 → way_behind、残り2回
    sessions = [_sess(2, "strength_training"), _sess(10, "strength_training"), _sess(1, "running")]
    st = build_status(sessions, [], NOW)
    assert st["past"]["week_strength"] == 1
    assert st["past"]["strength_14d"] == 2
    assert st["past"]["week_cardio"] == 1
    assert st["now"]["verdict"] == "way_behind"
    assert st["next"]["remaining_this_week"] == 2


def test_behind_two_sessions():
    sessions = [_sess(1, "strength_training"), _sess(4, "strength_training")]
    st = build_status(sessions, [], NOW)
    assert st["now"]["verdict"] == "behind"
    assert st["next"]["remaining_this_week"] == 1


def test_enough_when_target_met():
    sessions = [_sess(1, "strength_training"), _sess(3, "strength_training"), _sess(5, "strength_training")]
    st = build_status(sessions, [], NOW)
    assert st["now"]["verdict"] == "enough"
    assert st["next"]["remaining_this_week"] == 0


def test_same_day_counts_once():
    # 同日2セッションは1回
    d = _sess(2, "strength_training")
    st = build_status([d, dict(d)], [], NOW)
    assert st["past"]["week_strength"] == 1


def test_recovery_buckets_from_groups():
    groups = [
        {"recovery_pct": 100}, {"recovery_pct": 85}, {"recovery_pct": 60}, {"recovery_pct": 20},
    ]
    st = build_status([], groups, NOW)
    assert st["now"]["recovered"] == 2 and st["now"]["recovering"] == 1 and st["now"]["loaded"] == 1
