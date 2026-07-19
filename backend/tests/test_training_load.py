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


def test_gross_overshoot_escalates_immediately():
    # 8kg×23回 は目標(10)を大幅超過 = 軽すぎ。1セッションでも即昇量する
    # (据え置いて RIR2@8-10 のような達成不能指示を出さない)
    hist = [{"date": date(2026, 7, 6), "weight_kg": 8.0, "reps": 23}]
    s = suggest_for_exercise(history=hist, today=TODAY, starting_weight=None)
    assert s["suggested_weight_kg"] == 12.0
    assert "大幅超過" in s["basis"]


def test_gross_overshoot_at_max_weight_switches_to_variation():
    # 手持ち最大(20kg)で大幅超過 → 昇量できないので難種目/テンポで強度を上げる
    hist = [{"date": date(2026, 7, 6), "weight_kg": 20.0, "reps": 20}]
    s = suggest_for_exercise(history=hist, today=TODAY, starting_weight=None)
    assert s["suggested_weight_kg"] == 20.0
    assert "難種目" in s["basis"] or "テンポ" in s["basis"]


def test_deload_after_long_gap():
    hist = [{"date": date(2026, 6, 20), "weight_kg": 12.0, "reps": 10}]
    s = suggest_for_exercise(history=hist, today=TODAY, starting_weight=None)
    assert s["suggested_weight_kg"] == 8.0  # 1段階下げて再開
    assert "deload" in s["basis"]


def test_parse_sets_reads_grams_and_bodyweight():
    from app.scoring.training_load import _parse_sets

    raw = {"summarizedExerciseSets": [
        {"category": "DEADLIFT", "subCategory": "ROMANIAN_DEADLIFT", "reps": 11, "maxWeight": 8000, "sets": 1},
        {"category": "PUSH_UP", "reps": 12, "maxWeight": 0, "sets": 1},
        {"category": "CORE", "subCategory": "KNEELING_AB_WHEEL", "reps": 30, "maxWeight": 0},
    ]}
    got = _parse_sets(raw)
    assert {"label": "ルーマニアンデッドリフト", "weight_kg": 8.0, "reps": 11} in got
    assert {"label": "腕立て", "weight_kg": 0.0, "reps": 12} in got
    assert {"label": "アブローラー", "weight_kg": 0.0, "reps": 30} in got


def test_bodyweight_progresses_by_reps_not_weight():
    # 前回 腕立て12回 (自重) → 次は据え置きでなく回数を増やす (ぬるま湯回避)
    hist = [{"date": date(2026, 7, 6), "weight_kg": 0.0, "reps": 12}]
    s = suggest_for_exercise(history=hist, today=TODAY, starting_weight=None)
    assert s["suggested_weight_kg"] == 0.0
    assert "12" in s["basis"] or "回" in s["basis"]
    # 目標レップに達したら難種目へ
    hard = suggest_for_exercise(
        history=[{"date": date(2026, 7, 6), "weight_kg": 0.0, "reps": 25}], today=TODAY, starting_weight=None
    )
    assert "難" in hard["basis"] or "変" in hard["basis"]
