from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.notifications.engine import collect_due_notifications

JST = ZoneInfo("Asia/Tokyo")


def _now(h: int, m: int = 0) -> datetime:
    return datetime(2026, 6, 21, h, m, tzinfo=JST)


def _critical_alert(code="chronic_sleep_deficit", title="慢性睡眠不足"):
    return {"code": code, "severity": "critical", "title": title, "detail": "d", "action": "a"}


def _action(time_jst, priority="high", title="ナップ20分", why="眠気対策"):
    return {"time_jst": time_jst, "priority": priority, "title": title, "why": why}


# --- critical アラート digest ---


def test_critical_alert_emits_digest_after_morning_hour():
    out = collect_due_notifications(now=_now(8), alerts=[_critical_alert()])
    assert len(out) == 1
    n = out[0]
    assert n.dedup_key == "alert:2026-06-21"
    assert n.priority == "critical"
    assert "慢性睡眠不足" in n.body


def test_critical_alert_suppressed_before_morning_hour():
    # 5 時はまだ就寝中想定 → 鳴らさない
    out = collect_due_notifications(now=_now(5), alerts=[_critical_alert()])
    assert out == []


def test_multiple_criticals_are_merged_into_one_digest():
    alerts = [_critical_alert(title="慢性睡眠不足"), _critical_alert(code="weight_loss", title="低体重域")]
    out = collect_due_notifications(now=_now(9), alerts=alerts)
    assert len(out) == 1
    assert "慢性睡眠不足" in out[0].body
    assert "低体重域" in out[0].body


def test_warning_and_info_alerts_are_ignored():
    alerts = [
        {"code": "hrv_chronic_decline", "severity": "warning", "title": "HRV低下"},
        {"code": "sleep_irregular", "severity": "info", "title": "リズム乱れ"},
    ]
    out = collect_due_notifications(now=_now(10), alerts=alerts)
    assert out == []


# --- 時間依存アクション ---


def test_high_action_fires_at_its_time():
    out = collect_due_notifications(now=_now(14, 30), advice_actions=[_action("14:30")])
    assert len(out) == 1
    assert out[0].priority == "high"
    assert out[0].dedup_key.startswith("action:2026-06-21:14:30:")


def test_action_within_window_still_fires():
    # 14:30 のアクションを 15:00 に評価 (window 60 分内) → 出る
    out = collect_due_notifications(now=_now(15, 0), advice_actions=[_action("14:30")])
    assert len(out) == 1


def test_action_past_window_does_not_fire():
    # 14:30 を 16:00 に評価 (90 分後 > window) → 出さない (古いリマインドの一斉送信防止)
    out = collect_due_notifications(now=_now(16, 0), advice_actions=[_action("14:30")])
    assert out == []


def test_action_before_its_time_does_not_fire():
    out = collect_due_notifications(now=_now(14, 0), advice_actions=[_action("14:30")])
    assert out == []


def test_mid_and_low_priority_actions_ignored():
    actions = [_action("14:30", priority="mid"), _action("14:30", priority="low")]
    out = collect_due_notifications(now=_now(14, 30), advice_actions=actions)
    assert out == []


def test_action_without_time_ignored():
    out = collect_due_notifications(now=_now(14, 30), advice_actions=[_action(None)])
    assert out == []


def test_critical_action_maps_to_critical_priority():
    out = collect_due_notifications(now=_now(14, 30), advice_actions=[_action("14:30", priority="critical")])
    assert out[0].priority == "critical"


# --- 就寝リマインド ---


def test_bedtime_reminder_fires_before_bedtime():
    # 就寝 23:00 → 22:45 にリマインド。22:45 に評価で出る。
    out = collect_due_notifications(
        now=_now(22, 45), tonight_plan={"bedtime": "23:00"}, bedtime_reminder=True
    )
    keys = [n.dedup_key for n in out]
    assert "bedtime:2026-06-21" in keys


def test_bedtime_reminder_disabled():
    out = collect_due_notifications(
        now=_now(22, 45), tonight_plan={"bedtime": "23:00"}, bedtime_reminder=False
    )
    assert out == []


def test_bedtime_reminder_not_yet():
    out = collect_due_notifications(
        now=_now(20, 0), tonight_plan={"bedtime": "23:00"}, bedtime_reminder=True
    )
    assert out == []


# --- 統合・順序 ---


def test_results_sorted_critical_first():
    out = collect_due_notifications(
        now=_now(14, 30),
        alerts=[_critical_alert()],
        advice_actions=[_action("14:30", priority="high")],
    )
    assert [n.priority for n in out] == ["critical", "high"]


def test_empty_inputs_produce_nothing():
    assert collect_due_notifications(now=_now(12)) == []
