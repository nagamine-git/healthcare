"""recommend_wind_down: 「すぐ寝ろ」vs 呼吸法 (cyclic_sigh / slow_6) vs 不要 の4分岐。"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.scoring.wind_down import recommend_wind_down

JST = ZoneInfo("Asia/Tokyo")


def _base(**overrides):
    """デフォルト: 就寝1h前・過覚醒兆候なし・カフェイン残量なし → none になる状態。"""
    now = overrides.pop("now", datetime(2026, 7, 21, 21, 0, tzinfo=JST))
    target_bedtime = overrides.pop(
        "target_bedtime", datetime(2026, 7, 21, 23, 0, tzinfo=JST)
    )
    kwargs = dict(
        now=now,
        target_bedtime=target_bedtime,
        sleep_debt_min=None,
        hrv_last=None,
        hrv_baseline=None,
        resting_hr=None,
        resting_hr_baseline=None,
        caffeine_mg_on_board=None,
    )
    kwargs.update(overrides)
    return recommend_wind_down(**kwargs)


# ----- 1. すぐ寝ろ -----


def test_past_bedtime_triggers_sleep_now():
    now = datetime(2026, 7, 21, 23, 30, tzinfo=JST)
    target_bedtime = datetime(2026, 7, 21, 23, 0, tzinfo=JST)  # 30分前に過ぎた
    out = _base(now=now, target_bedtime=target_bedtime)
    assert out["action"] == "sleep_now"
    assert out["protocol"] is None
    assert out["minutes"] == 0
    assert "睡眠" in out["reason"]
    assert out["headline"] == "すぐ寝る"


def test_large_sleep_debt_and_bedtime_soon_triggers_sleep_now():
    # まだ就寝目標前 (残り10分) だが、睡眠負債が大きい (閾値90分デフォルト超え)
    now = datetime(2026, 7, 21, 22, 50, tzinfo=JST)
    target_bedtime = datetime(2026, 7, 21, 23, 0, tzinfo=JST)
    out = _base(now=now, target_bedtime=target_bedtime, sleep_debt_min=120.0)
    assert out["action"] == "sleep_now"
    assert out["minutes"] == 0


def test_large_sleep_debt_but_bedtime_not_soon_does_not_trigger_sleep_now():
    # 睡眠負債は大きいが、就寝目標まで残り時間がまだ十分 (デフォルト閾値20分より前)
    now = datetime(2026, 7, 21, 21, 0, tzinfo=JST)
    target_bedtime = datetime(2026, 7, 21, 23, 0, tzinfo=JST)
    out = _base(now=now, target_bedtime=target_bedtime, sleep_debt_min=120.0)
    assert out["action"] != "sleep_now"


# ----- 2. サイクリック・サイ (強い過覚醒) -----


def test_strong_hrv_drop_triggers_cyclic_sigh():
    now = datetime(2026, 7, 21, 21, 0, tzinfo=JST)
    target_bedtime = datetime(2026, 7, 21, 23, 0, tzinfo=JST)  # wind-down 窓の外 (残り120分)
    out = _base(
        now=now, target_bedtime=target_bedtime,
        hrv_last=30.0, hrv_baseline=50.0,  # 40% 低下 (閾値30%超え)
    )
    assert out["action"] == "breathe"
    assert out["protocol"] == "cyclic_sigh"
    assert 3 <= out["minutes"] <= 5
    assert "Balban" in out["reason"] or "cyclic" in out["reason"]
    assert len(out["steps"]) == 3


def test_strong_rhr_rise_triggers_cyclic_sigh():
    now = datetime(2026, 7, 21, 21, 0, tzinfo=JST)
    target_bedtime = datetime(2026, 7, 21, 23, 0, tzinfo=JST)
    out = _base(
        now=now, target_bedtime=target_bedtime,
        resting_hr=68.0, resting_hr_baseline=58.0,  # +10bpm (閾値8bpm超え)
    )
    assert out["action"] == "breathe"
    assert out["protocol"] == "cyclic_sigh"


def test_cyclic_sigh_takes_priority_over_sleep_now_when_not_past_bedtime():
    # 過覚醒が強くても、まだ就寝目標を過ぎていなければ sleep_now より cyclic_sigh を優先
    now = datetime(2026, 7, 21, 21, 0, tzinfo=JST)
    target_bedtime = datetime(2026, 7, 21, 23, 0, tzinfo=JST)
    out = _base(
        now=now, target_bedtime=target_bedtime,
        hrv_last=20.0, hrv_baseline=50.0, sleep_debt_min=10.0,
    )
    assert out["action"] == "breathe"
    assert out["protocol"] == "cyclic_sigh"


# ----- 3. スロー共鳴呼吸 (wind-down窓 + 軽度過覚醒/カフェイン) -----


def test_mild_hyperarousal_in_window_triggers_slow6():
    # 就寝まで残り20分 (デフォルト窓45分以内) + 軽度 HRV 低下 (20%、strong閾値30%未満)
    now = datetime(2026, 7, 21, 22, 40, tzinfo=JST)
    target_bedtime = datetime(2026, 7, 21, 23, 0, tzinfo=JST)
    out = _base(
        now=now, target_bedtime=target_bedtime,
        hrv_last=40.0, hrv_baseline=50.0,  # 20% 低下
    )
    assert out["action"] == "breathe"
    assert out["protocol"] == "slow_6"
    assert 5 <= out["minutes"] <= 10
    assert len(out["steps"]) == 3


def test_caffeine_residual_in_window_triggers_slow6():
    now = datetime(2026, 7, 21, 22, 50, tzinfo=JST)
    target_bedtime = datetime(2026, 7, 21, 23, 0, tzinfo=JST)
    out = _base(now=now, target_bedtime=target_bedtime, caffeine_mg_on_board=50.0)
    assert out["action"] == "breathe"
    assert out["protocol"] == "slow_6"


def test_mild_hyperarousal_outside_window_does_not_trigger_slow6():
    # 軽度の過覚醒だが、まだ wind-down 窓 (就寝45分前) の外 → slow_6 は出さない
    now = datetime(2026, 7, 21, 20, 0, tzinfo=JST)
    target_bedtime = datetime(2026, 7, 21, 23, 0, tzinfo=JST)  # 残り3時間
    out = _base(
        now=now, target_bedtime=target_bedtime,
        hrv_last=40.0, hrv_baseline=50.0,  # 20% 低下 (mild)
    )
    assert out["action"] == "none"


# ----- 4. 不要 -----


def test_calm_state_far_from_bedtime_is_none():
    now = datetime(2026, 7, 21, 20, 0, tzinfo=JST)
    target_bedtime = datetime(2026, 7, 21, 23, 0, tzinfo=JST)
    out = _base(now=now, target_bedtime=target_bedtime)
    assert out["action"] == "none"
    assert out["protocol"] is None
    assert out["minutes"] == 0
    assert "落ち着いている" in out["reason"]


def test_calm_state_inside_window_is_still_none():
    # wind-down 窓内でも過覚醒兆候・カフェインが無ければ none のまま
    now = datetime(2026, 7, 21, 22, 40, tzinfo=JST)
    target_bedtime = datetime(2026, 7, 21, 23, 0, tzinfo=JST)
    out = _base(now=now, target_bedtime=target_bedtime)
    assert out["action"] == "none"


# ----- 診断フィールド -----


def test_diagnostic_fields_present():
    now = datetime(2026, 7, 21, 21, 0, tzinfo=JST)
    target_bedtime = datetime(2026, 7, 21, 23, 0, tzinfo=JST)
    out = _base(
        now=now, target_bedtime=target_bedtime,
        hrv_last=45.0, hrv_baseline=50.0, resting_hr=60.0, resting_hr_baseline=58.0,
    )
    assert out["minutes_to_bedtime"] == 120.0
    assert out["hrv_drop_pct"] == 0.1
    assert out["rhr_rise_bpm"] == 2.0
