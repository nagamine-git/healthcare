"""実績ベース負荷提案 (double progression) 純関数テスト。"""

from __future__ import annotations

from datetime import date

from app.scoring.training_load import suggest_for_exercise

TODAY = date(2026, 7, 8)


def test_first_time_uses_level_scaled_start():
    s = suggest_for_exercise(history=[], today=TODAY, starting_weight=8.0, level="beginner")
    assert s["suggested_weight_kg"] == 8.0
    s2 = suggest_for_exercise(history=[], today=TODAY, starting_weight=8.0, level="advanced")
    assert s2["suggested_weight_kg"] == 12.0  # 8×1.5=12 → 手持ち12kg


def test_progresses_after_two_sessions_at_target_reps():
    hist = [
        {"date": date(2026, 7, 6), "weight_kg": 8.0, "reps": 10},
        {"date": date(2026, 7, 3), "weight_kg": 8.0, "reps": 10},
    ]
    s = suggest_for_exercise(history=hist, today=TODAY, starting_weight=None)
    assert s["suggested_weight_kg"] == 12.0  # 次の手持ち重量へ昇量
    assert "昇量" in s["basis"]


def test_stays_when_reps_not_yet_met():
    hist = [{"date": date(2026, 7, 6), "weight_kg": 8.0, "reps": 8}]
    s = suggest_for_exercise(history=hist, today=TODAY, starting_weight=None)
    assert s["suggested_weight_kg"] == 8.0


def test_deload_after_long_gap():
    hist = [{"date": date(2026, 6, 20), "weight_kg": 12.0, "reps": 10}]
    s = suggest_for_exercise(history=hist, today=TODAY, starting_weight=None)
    assert s["suggested_weight_kg"] == 8.0  # 1段階下げて再開
    assert "deload" in s["basis"]
