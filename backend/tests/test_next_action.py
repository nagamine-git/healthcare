"""「いまコレ」候補生成 (build_candidates) の純関数テスト。DB 不要。"""

from __future__ import annotations

from datetime import datetime

from app.scoring.next_action import Inputs, build_candidates


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


def test_training_gap_suppressed_only_on_low_morning_bb():
    # 朝BBが本当に低い日 (回復不良) は休む
    low = Inputs(days_since_strength=4, strength_days_14=2, morning_bb=25.0)
    assert all(c["key"] != "training_gap" for c in build_candidates(low, _at(15)))
    # 夜の bb_current が低くても朝BBが高ければ出す (鶏卵回避)
    ok = Inputs(days_since_strength=4, strength_days_14=2, morning_bb=70.0, bb_current=12.0)
    assert any(c["key"] == "training_gap" for c in build_candidates(ok, _at(20)))


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
