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
    """rep 上限を達成したら**まずセットを増やす** (重量はまだ上げない)。

    仕様変更: 固定式ダンベルは 8→12kg で +50% 跳ぶため、即昇量すると
    「上がらないか軽すぎるか」の二択になる。3→4 セット (+33%) を挟んで断崖を埋める。
    重量が上がるのはセットも上限に達してから (test_weight_raised_only_after_set_ceiling)。
    """
    hist = [
        {"date": date(2026, 7, 6), "weight_kg": 8.0, "reps": 10, "sets": 3},
        {"date": date(2026, 7, 3), "weight_kg": 8.0, "reps": 10, "sets": 3},
    ]
    s = suggest_for_exercise(history=hist, today=TODAY, starting_weight=None)
    assert s["suggested_weight_kg"] == 8.0   # 据え置き
    assert s["suggested_sets"] == 4          # 先にセットで積む
    assert "セット" in s["basis"]


def test_stays_when_reps_not_yet_met():
    hist = [{"date": date(2026, 7, 6), "weight_kg": 8.0, "reps": 8}]
    s = suggest_for_exercise(history=hist, today=TODAY, starting_weight=None)
    assert s["suggested_weight_kg"] == 8.0


def test_gross_overshoot_escalates_immediately():
    # 8kg×23回 は目標(10)を大幅超過 = 軽すぎ。1セッションでも即昇量する
    # (据え置いて RIR2@8-10 のような達成不能指示を出さない)
    hist = [{"date": date(2026, 7, 6), "weight_kg": 8.0, "reps": 23}]
    s = suggest_for_exercise(history=hist, today=TODAY, starting_weight=None)
    assert s["suggested_weight_kg"] == 12.0  # 固定式: 8→12
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
    assert s["suggested_weight_kg"] == 8.0  # 1段階下げて再開 (固定式: 12→8)
    assert "deload" in s["basis"]


def test_parse_sets_reads_grams_and_bodyweight():
    from app.scoring.training_load import _parse_sets

    raw = {"summarizedExerciseSets": [
        {"category": "DEADLIFT", "subCategory": "ROMANIAN_DEADLIFT", "reps": 11, "maxWeight": 8000, "sets": 1},
        {"category": "PUSH_UP", "reps": 12, "maxWeight": 0, "sets": 1},
        {"category": "CORE", "subCategory": "KNEELING_AB_WHEEL", "reps": 30, "maxWeight": 0},
    ]}
    # dict 完全一致で見ない (total_reps/sets のような診断フィールドの追加で壊れるため、
    # 検証したい値だけを取り出して比べる)
    got = {r["label"]: r for r in _parse_sets(raw)}
    for label, weight, reps in (
        ("ルーマニアンデッドリフト", 8.0, 11),
        ("腕立て", 0.0, 12),
        ("アブローラー", 0.0, 30),
    ):
        assert got[label]["weight_kg"] == weight
        assert got[label]["reps"] == reps  # sets=1 (or 未指定) なので合計=1セット分


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


# ----- summarizedExerciseSets の reps は「全セット合計」-----


def test_parse_sets_divides_total_reps_by_set_count():
    """Garmin の reps は種目の全セット合計。1セットあたりに割って返すこと。

    回帰テスト: 割らずに閾値 (_TARGET_REPS=10 / _OVERSHOOT_REPS=15 は **1セットあたり**)
    と比べていたため、「3セットこなす = 合計が閾値を超える」だけで毎回「軽すぎ」と
    誤判定されていた。実際 12kg×26rep(3セット=約8.7回/セット) が「大幅超過」とされ
    16kg へ昇量された。腰の既往がある中で過大な重量を処方しかねない。
    """
    from app.scoring.training_load import _parse_sets

    raw = {"summarizedExerciseSets": [
        {"category": "SQUAT", "subCategory": "GOBLET_SQUAT",
         "reps": 39, "sets": 3, "maxWeight": 8000},
    ]}
    (row,) = _parse_sets(raw)
    assert row["reps"] == 13          # 39 / 3 セット
    assert row["total_reps"] == 39    # 元の合計も残す
    assert row["sets"] == 3
    assert row["weight_kg"] == 8.0    # maxWeight はグラム


def test_on_target_volume_does_not_trigger_overshoot_upgrade():
    """目標どおり (8-10rep×3セット) こなしただけで昇量しないこと。"""
    from datetime import date, timedelta

    from app.scoring.training_load import _parse_sets, suggest_for_exercise

    raw = {"summarizedExerciseSets": [
        # 12kg を 3セット合計26回 = 約8.7回/セット。目標 8-10 の範囲内
        {"category": "ROW", "subCategory": None, "reps": 26, "sets": 3, "maxWeight": 12000},
    ]}
    (row,) = _parse_sets(raw)
    today = date(2026, 7, 28)
    out = suggest_for_exercise(
        history=[{"date": today - timedelta(days=2), **row}], today=today,
        starting_weight=None,
    )
    # 12kg 据え置き (16kg へ跳ね上げない)
    assert out["suggested_weight_kg"] == 12.0
    assert "大幅超過" not in out["basis"]


def test_genuine_overshoot_still_upgrades():
    """本当に軽すぎる場合 (1セットあたりが閾値超) は従来どおり昇量する。"""
    from datetime import date, timedelta

    from app.scoring.training_load import _parse_sets, suggest_for_exercise

    raw = {"summarizedExerciseSets": [
        # 8kg を 3セット合計60回 = 20回/セット。明確に軽すぎ
        {"category": "CURL", "subCategory": None, "reps": 60, "sets": 3, "maxWeight": 8000},
    ]}
    (row,) = _parse_sets(raw)
    today = date(2026, 7, 28)
    out = suggest_for_exercise(
        history=[{"date": today - timedelta(days=2), **row}], today=today,
        starting_weight=None,
    )
    assert out["suggested_weight_kg"] > 8.0
    assert "大幅超過" in out["basis"]


# ----- 重量の刻みが粗い問題: セット段で断崖を埋める -----


def _hist(weight, reps, sets, days_ago, today):
    from datetime import timedelta
    return {"date": today - timedelta(days=days_ago), "weight_kg": weight,
            "reps": reps, "sets": sets}


def test_rep_ceiling_adds_a_set_before_raising_weight():
    """rep 上限に達しても、いきなり 12→16kg (+33%) に跳ばず先にセットを増やす。"""
    from datetime import date

    from app.scoring.training_load import suggest_for_exercise

    today = date(2026, 7, 28)
    hist = [_hist(12.0, 10, 3, 2, today), _hist(12.0, 10, 3, 5, today)]
    out = suggest_for_exercise(history=hist, today=today, starting_weight=None)

    assert out["suggested_weight_kg"] == 12.0   # 据え置き
    assert out["suggested_sets"] == 4           # 3→4 セット (+33% ボリューム)


def test_weight_raised_only_after_set_ceiling():
    """セットも上限まで積んだら昇量し、セット数は基準に戻す。"""
    from datetime import date

    from app.scoring.training_load import suggest_for_exercise

    today = date(2026, 7, 28)
    hist = [_hist(12.0, 10, 4, 2, today), _hist(12.0, 10, 4, 5, today)]
    out = suggest_for_exercise(history=hist, today=today, starting_weight=None)

    assert out["suggested_weight_kg"] == 16.0
    assert out["suggested_sets"] == 3            # 増やしたセットは戻す
    assert "下ろし3秒" in out["basis"]           # 大きい跳びには着地の指示を添える


def test_below_rep_target_keeps_weight_and_sets():
    """rep 上限に届いていなければ従来どおり rep を積む (セットは増やさない)。"""
    from datetime import date

    from app.scoring.training_load import suggest_for_exercise

    today = date(2026, 7, 28)
    hist = [_hist(12.0, 9, 3, 2, today)]
    out = suggest_for_exercise(history=hist, today=today, starting_weight=None)

    assert out["suggested_weight_kg"] == 12.0
    assert out["suggested_sets"] == 3


def test_all_branches_expose_suggested_sets():
    """どの分岐でも suggested_sets を返す (呼び出し側でキー有無を分岐させない)。"""
    from datetime import date

    from app.scoring.training_load import suggest_for_exercise

    today = date(2026, 7, 28)
    cases = [
        [],                                        # 初回
        [_hist(0.0, 12, 3, 2, today)],             # 自重
        [_hist(12.0, 8, 3, 30, today)],            # deload
        [_hist(8.0, 20, 3, 2, today)],             # 大幅超過
        [_hist(20.0, 20, 4, 2, today)],            # 手持ち最大
    ]
    for hist in cases:
        out = suggest_for_exercise(history=hist, today=today, starting_weight=None)
        assert "suggested_sets" in out, out["basis"]
        assert out["suggested_sets"] >= 1
