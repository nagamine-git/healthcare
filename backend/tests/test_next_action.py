"""「いまコレ」候補生成 (build_candidates) の純関数テスト。DB 不要。"""

from __future__ import annotations

from datetime import datetime

from app.scoring.next_action import Inputs, build_candidates, recommend_nap


def _at(h: int, m: int = 0) -> datetime:
    return datetime(2026, 7, 3, h, m)


def _keys(cands):
    return [c["key"] for c in sorted(cands, key=lambda x: -x["priority"])]


def test_critical_alert_wins_over_everything():
    inp = Inputs(
        alerts=[{"severity": "critical", "title": "SpO2低下", "action": "受診を検討"}],
        bb_current=10.0,  # 仮眠候補も出る状況
        checkin_done=False,
    )
    keys = _keys(build_candidates(inp, _at(14)))
    assert keys[0] == "alert_critical"
    assert "nap" in keys  # 次点には残る


def test_garmin_not_worn_fires_in_daytime_only():
    inp = Inputs(minutes_since_hr=200.0)
    assert "garmin_wear" in _keys(build_candidates(inp, _at(14)))
    assert "garmin_wear" not in _keys(build_candidates(inp, _at(23, 30)))  # 夜間は着けてなくても騒がない


def test_water_pace_deficit():
    # 15:00 = 起床帯の半分経過 → 期待 1000ml。実績 200ml → 不足 800ml
    inp = Inputs(water_actual_ml=200.0, water_ideal_ml=2000.0)
    cands = build_candidates(inp, _at(15))
    water = next(c for c in cands if c["key"] == "water")
    assert water["priority"] == 55  # 500ml 以上の不足は高め
    # 朝イチはまだ期待値が小さいので出ない
    assert all(c["key"] != "water" for c in build_candidates(inp, _at(8)))


def test_bedtime_prep_window_and_caffeine_cutoff():
    inp = Inputs(tonight={"bath": "22:00", "bedtime": "23:30"})
    # 22:10 = 入浴ウィンドウ内 → 就寝準備が最優先級
    keys = _keys(build_candidates(inp, _at(22, 10)))
    assert keys[0] == "bedtime_prep"
    # 17:15 = カットオフ(17:30) の 15 分前 → カフェイン最終案内
    cands = build_candidates(inp, _at(17, 15))
    assert any(c["key"] == "caffeine_cutoff" for c in cands)


def test_advice_action_due_now():
    inp = Inputs(advice_actions=[
        {"time_jst": "14:30", "title": "上半身プッシュ", "priority": "high"},
        {"time_jst": "20:00", "title": "ストレッチ", "priority": "low"},  # low は対象外
    ])
    cands = build_candidates(inp, _at(14, 40))
    due = [c for c in cands if c["key"] == "advice_due"]
    assert len(due) == 1 and "上半身プッシュ" in due[0]["title"]


def test_hygiene_and_low_urgency_fillers():
    inp = Inputs(checkin_done=False, intervention_logged=False, journal_done=False,
                 cashflow_days_old=60)
    keys = _keys(build_candidates(inp, _at(21)))
    # 記録衛生 > 資産更新 > 学習 の順で全部並ぶ
    assert keys.index("intervention_log") < keys.index("checkin") < keys.index("journal")
    assert keys.index("journal") < keys.index("money_update") < keys.index("learning")


def test_quiet_afternoon_falls_back_to_learning():
    inp = Inputs(checkin_done=True, intervention_logged=True, journal_done=True,
                 cashflow_days_old=3)
    keys = _keys(build_candidates(inp, _at(15)))
    assert keys[0] == "learning"

def test_training_gap_pushes_under_trainer_even_in_evening():
    # 朝BB満タン・夜(20時)でも、週頻度が不足なら背中を押す (鶏卵修正の核)
    inp = Inputs(days_since_strength=4, strength_days_14=2, morning_bb=70.0, bb_current=20.0)
    tg = next(c for c in build_candidates(inp, _at(20)) if c["key"] == "training_gap")
    assert tg["priority"] == 66  # under-training 底上げ (water/protein より上)
    assert "目標 週3回に不足" in tg["why"]


def test_training_gap_escalates_at_5_days_when_behind():
    inp = Inputs(days_since_strength=6, strength_days_14=1, morning_bb=65.0)
    tg = next(c for c in build_candidates(inp, _at(15)) if c["key"] == "training_gap")
    assert tg["priority"] == 70
    assert "HIIT" in tg["title"]  # 朝BB高ければ高強度もメニュー


def test_training_gap_lower_priority_when_frequency_met():
    # 週3回 (14日6回) 達成済みなら控えめ (56)
    inp = Inputs(days_since_strength=3, strength_days_14=6, morning_bb=65.0)
    tg = next(c for c in build_candidates(inp, _at(15)) if c["key"] == "training_gap")
    assert tg["priority"] == 56


def test_training_gap_suppressed_only_on_depleted_morning_bb():
    # BB は弱い補助信号: 朝BBがほぼ枯渇 (<5) の極端な日だけ push を控える
    depleted = Inputs(days_since_strength=4, strength_days_14=2, morning_bb=3.0)
    assert all(c["key"] != "training_gap" for c in build_candidates(depleted, _at(15)))
    # 朝BBが 25 程度 (低め) でも枯渇ではないので push は止めない (BB非依存化)
    low = Inputs(days_since_strength=4, strength_days_14=2, morning_bb=25.0)
    assert any(c["key"] == "training_gap" for c in build_candidates(low, _at(15)))
    # 夜の bb_current が低くても朝BBが高ければ出す (鶏卵回避)
    ok = Inputs(days_since_strength=4, strength_days_14=2, morning_bb=70.0, bb_current=12.0)
    assert any(c["key"] == "training_gap" for c in build_candidates(ok, _at(20)))


def test_training_gap_intensity_gated_by_sleep_not_bb():
    # 強度可否は前夜睡眠で判断 (BB非依存)。目標比 -90分超の寝不足なら高強度メニューを出さない
    short = Inputs(days_since_strength=4, strength_days_14=2, morning_bb=70.0,
                   last_night_min=300, target_sleep_min=480)
    tg = next(c for c in build_candidates(short, _at(15)) if c["key"] == "training_gap")
    assert "HIIT" not in tg["title"]
    # 十分眠れていれば朝BBに関係なく高強度も提示
    rested = Inputs(days_since_strength=4, strength_days_14=2, morning_bb=20.0,
                    last_night_min=470, target_sleep_min=480)
    tg2 = next(c for c in build_candidates(rested, _at(15)) if c["key"] == "training_gap")
    assert "HIIT" in tg2["title"]


def test_atlas_focus_concrete_action_for_economy():
    # 抽象的な「一手を割く」ではなく、今日できる具体アクションを title に出す
    inp = Inputs(atlas_focus={"key": "economy", "label": "資産",
                              "score": 12, "weight": 1.5, "pri": 132})
    c = next(c for c in build_candidates(inp, _at(15)) if c["key"] == "atlas_focus")
    assert "円以上" in c["title"] and "保留" in c["title"]
    assert "資産" in c["why"]  # 達成度・重みの文脈は why に残す


def test_atlas_focus_condition_routes_to_sleep_tab():
    inp = Inputs(atlas_focus={"key": "condition", "label": "コンディション (日次)",
                              "score": 40, "weight": 1.5, "pri": 90})
    c = next(c for c in build_candidates(inp, _at(15)) if c["key"] == "atlas_focus")
    assert "就寝" in c["title"]
    assert c["link"] == "#tab-sleep"


def test_atlas_focus_unknown_key_falls_back():
    inp = Inputs(atlas_focus={"key": "mystery", "label": "謎",
                              "score": 10, "weight": 1.0, "pri": 90})
    c = next(c for c in build_candidates(inp, _at(15)) if c["key"] == "atlas_focus")
    assert "一手を割く" in c["title"]


def test_training_gap_suppressed_when_trained_today():
    inp = Inputs(days_since_strength=4, strength_days_14=2, trained_today=True, morning_bb=70.0)
    assert all(c["key"] != "training_gap" for c in build_candidates(inp, _at(15)))


def test_training_gap_bedtime_switches_to_short_session():
    inp = Inputs(days_since_strength=4, strength_days_14=2, morning_bb=70.0,
                 tonight={"bedtime": "23:30"})
    # 21時前だが就寝3h前 (20:30以降) → 短時間メニュー
    tg = next(c for c in build_candidates(inp, _at(20, 45)) if c["key"] == "training_gap")
    assert "短時間" in tg["title"]


def test_training_gap_quiet_within_1_day():
    inp = Inputs(days_since_strength=1, strength_days_14=3, morning_bb=70.0)
    assert all(c["key"] != "training_gap" for c in build_candidates(inp, _at(15)))


# ===== 仮眠の科学ベース睡眠時間計算 (recommend_nap) =====


def test_nap_defaults_to_power_nap_20min():
    # BB枯渇・時間に余裕・睡眠負債なし → 睡眠慣性を避ける20分パワーナップ
    plan = recommend_nap(_at(13), bb_current=15.0, last_night_min=480,
                         bedtime=_at(23, 30), target_sleep_min=480)
    assert plan is not None
    assert plan["kind"] == "power"
    assert plan["minutes"] == 20


def test_nap_full_cycle_when_sleep_deprived_and_time_allows():
    # 前夜5h (負債180分)・13時・遅い就寝 → 1睡眠周期の90分
    plan = recommend_nap(_at(13), bb_current=15.0, last_night_min=300,
                         bedtime=_at(23, 30), target_sleep_min=480)
    assert plan is not None
    assert plan["kind"] == "cycle"
    assert plan["minutes"] == 90


def test_nap_never_enters_grog_zone_when_time_is_short():
    # 15:45 → カットオフ16:00まで15分。負債大でも90分は不可。30-60分帯にも絶対入れない
    plan = recommend_nap(_at(15, 45), bb_current=15.0, last_night_min=300,
                         bedtime=_at(23, 30), target_sleep_min=480)
    assert plan is not None
    assert plan["kind"] == "power"
    assert plan["minutes"] <= 20
    assert not (30 <= plan["minutes"] <= 60)


def test_nap_suppressed_after_1600_cutoff():
    # 16:10 → 16:00 のカットオフを過ぎている → 遅い仮眠は夜間睡眠を削るので出さない
    assert recommend_nap(_at(16, 10), bb_current=15.0, last_night_min=480,
                         bedtime=_at(23, 30), target_sleep_min=480) is None


def test_nap_cutoff_pulled_earlier_by_early_bedtime():
    # 就寝19:00 → 6時間前=13:00 がカットオフ。13:30 は過ぎているので None
    assert recommend_nap(_at(13, 30), bb_current=15.0, last_night_min=480,
                         bedtime=_at(19, 0), target_sleep_min=480) is None


def test_nap_not_fired_when_energy_ok():
    # BBが十分 → 仮眠は提案しない
    assert recommend_nap(_at(13), bb_current=60.0, last_night_min=300,
                         bedtime=_at(23, 30), target_sleep_min=480) is None


def test_nap_power_when_late_afternoon_even_if_deprived():
    # 15:00・負債大でも 16:00 まで60分しかない → フルサイクル不可でパワーナップ
    plan = recommend_nap(_at(15), bb_current=15.0, last_night_min=300,
                         bedtime=_at(23, 30), target_sleep_min=480)
    assert plan is not None
    assert plan["kind"] == "power"


def test_nap_missing_sleep_data_degrades_to_power_nap():
    # 前夜データ欠測 → 負債0扱いでパワーナップ (堅牢な劣化)
    plan = recommend_nap(_at(13), bb_current=10.0, last_night_min=None,
                         bedtime=None, target_sleep_min=480)
    assert plan is not None
    assert plan["kind"] == "power"
    assert plan["minutes"] == 20


def test_nap_wired_into_candidates_with_calculated_duration():
    inp = Inputs(bb_current=15.0, last_night_min=480,
                 tonight={"bedtime": "23:30"}, target_sleep_min=480)
    nap = next(c for c in build_candidates(inp, _at(13)) if c["key"] == "nap")
    assert "20分" in nap["title"]
    assert "起床" in nap["title"]  # 起床時刻を提示


# ===== 就寝前: 今夜の睡眠実験 (sleep_experiment) =====


def test_sleep_experiment_fires_in_evening():
    inp = Inputs(
        sleep_experiment={"kind": "explore", "text": "今夜は耳栓を外して寝てみる", "reason": "比較のため"},
        tonight={"bedtime": "23:30"},
    )
    se = next(c for c in build_candidates(inp, _at(21)) if c["key"] == "sleep_experiment")
    assert "耳栓" in se["title"]
    assert se["why"] == "比較のため"


def test_sleep_experiment_quiet_in_daytime():
    inp = Inputs(sleep_experiment={"kind": "explore", "text": "今夜は耳栓を外して寝てみる", "reason": "x"})
    assert "sleep_experiment" not in _keys(build_candidates(inp, _at(14)))


def test_sleep_experiment_suppressed_when_already_logged():
    inp = Inputs(
        sleep_experiment={"kind": "explore", "text": "今夜は耳栓を外して寝てみる", "reason": "x"},
        intervention_logged=True,
    )
    assert "sleep_experiment" not in _keys(build_candidates(inp, _at(21)))


# ===== いまコレを達成度×重みで (atlas_focus) =====


def test_atlas_focus_rises_with_weight_and_gap():
    inp = Inputs(atlas_focus={"label": "資産", "score": 15, "weight": 3.0, "key": "economy", "pri": 255})
    c = next(x for x in build_candidates(inp, _at(14)) if x["key"] == "atlas_focus")
    # title は具体アクション、文脈(領域名・重み)は why 側に移動
    assert "円以上" in c["title"]
    assert "資産" in c["why"] and "×3.0" in c["why"]
    assert c["priority"] >= 80  # 伸びしろ×重みが大きいので上位


def test_atlas_focus_quiet_when_high_achievement_low_weight():
    # 達成98・重み1 → pri 小 → 出さない
    inp = Inputs(atlas_focus={"label": "健診", "score": 98, "weight": 1.0, "key": "checkup", "pri": 2})
    assert all(x["key"] != "atlas_focus" for x in build_candidates(inp, _at(14)))
