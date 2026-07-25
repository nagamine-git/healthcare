"""recommend_meditation: ストレス高→body_scan / 通常→breath_awareness / 時間不足→none の分岐。"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.scoring.meditation import recommend_meditation

JST = ZoneInfo("Asia/Tokyo")


def _base(**overrides):
    """デフォルト: 就寝1h前・ストレス不明 → breath_awareness になる状態。"""
    now = overrides.pop("now", datetime(2026, 7, 21, 22, 0, tzinfo=JST))
    target_bedtime = overrides.pop("target_bedtime", datetime(2026, 7, 21, 23, 0, tzinfo=JST))
    kwargs = dict(now=now, target_bedtime=target_bedtime, stress_level=None)
    kwargs.update(overrides)
    return recommend_meditation(**kwargs)


# ----- 高ストレス → body_scan -----


def test_high_stress_triggers_body_scan():
    out = _base(stress_level=4)  # デフォルト閾値4以上
    assert out["action"] == "meditate"
    assert out["protocol"] == "body_scan"
    assert "Ong" in out["reason"]
    assert len(out["steps"]) == 4
    assert out["bell_interval_sec"] is None  # 部位切り替えで自然に再アンカーされるため


def test_max_stress_triggers_body_scan():
    out = _base(stress_level=5)
    assert out["protocol"] == "body_scan"


def test_low_stress_does_not_trigger_body_scan():
    out = _base(stress_level=2)
    assert out["protocol"] != "body_scan"


# ----- 通常 (低ストレス/不明) → breath_awareness -----


def test_no_stress_info_triggers_breath_awareness():
    out = _base(stress_level=None)
    assert out["action"] == "meditate"
    assert out["protocol"] == "breath_awareness"
    assert "Black" in out["reason"]
    assert len(out["steps"]) == 3
    assert out["bell_interval_sec"] == 90  # 単一セグメントなのでベルで再アンカー


def test_mild_stress_triggers_breath_awareness():
    out = _base(stress_level=3)
    assert out["protocol"] == "breath_awareness"


# ----- 就寝目標超過/直前すぎる → none -----


def test_past_bedtime_triggers_none():
    now = datetime(2026, 7, 21, 23, 30, tzinfo=JST)
    target_bedtime = datetime(2026, 7, 21, 23, 0, tzinfo=JST)  # 30分前に過ぎた
    out = _base(now=now, target_bedtime=target_bedtime, stress_level=4)
    assert out["action"] == "none"
    assert out["protocol"] is None
    assert out["minutes"] == 0
    assert out["segments"] == []
    assert out["bell_interval_sec"] is None


def test_not_enough_time_for_breath_awareness_triggers_none():
    # breath_awareness の最低分数 (デフォルト5分) にも満たない残り時間
    now = datetime(2026, 7, 21, 22, 57, tzinfo=JST)
    target_bedtime = datetime(2026, 7, 21, 23, 0, tzinfo=JST)  # 残り3分
    out = _base(now=now, target_bedtime=target_bedtime, stress_level=None)
    assert out["action"] == "none"


def test_enough_time_for_breath_awareness_but_not_body_scan_falls_back_correctly():
    # body_scan の最低分数 (デフォルト8分) には満たないが breath_awareness (5分) には足りる残り時間
    # → 高ストレスでも body_scan には満たないので breath_awareness ではなく none になる
    #   (このモジュールはプロトコルを先に決めてから時間判定するため、途中で切り替えない)
    now = datetime(2026, 7, 21, 22, 53, tzinfo=JST)
    target_bedtime = datetime(2026, 7, 21, 23, 0, tzinfo=JST)  # 残り7分
    out = _base(now=now, target_bedtime=target_bedtime, stress_level=4)
    assert out["action"] == "none"


# ----- 分数が就寝までの残り時間に収まる -----


def test_minutes_capped_by_remaining_time():
    now = datetime(2026, 7, 21, 22, 50, tzinfo=JST)
    target_bedtime = datetime(2026, 7, 21, 23, 0, tzinfo=JST)  # 残り10分
    out = _base(now=now, target_bedtime=target_bedtime, stress_level=None)
    assert out["minutes"] <= 10


def test_minutes_within_protocol_range_when_time_is_abundant():
    out = _base(stress_level=None)  # 残り60分、breath_awareness (デフォルト5-12分)
    assert 5 <= out["minutes"] <= 12


# ----- segments の秒数合計が minutes*60 と一致 -----


def test_body_scan_segments_sum_matches_minutes():
    out = _base(stress_level=4)
    total_sec = sum(seg["seconds"] for seg in out["segments"])
    assert total_sec == out["minutes"] * 60
    assert len(out["segments"]) == 12  # 足→...→頭 の標準12部位


def test_breath_awareness_segments_sum_matches_minutes():
    out = _base(stress_level=None)
    total_sec = sum(seg["seconds"] for seg in out["segments"])
    assert total_sec == out["minutes"] * 60
    assert len(out["segments"]) == 1


# ----- 診断フィールド -----


def test_diagnostic_fields_present():
    now = datetime(2026, 7, 21, 22, 0, tzinfo=JST)
    target_bedtime = datetime(2026, 7, 21, 23, 0, tzinfo=JST)
    out = _base(now=now, target_bedtime=target_bedtime, stress_level=3)
    assert out["minutes_to_bedtime"] == 60.0
    assert out["stress_level"] == 3


# ----- API 層: 主観ストレスの鮮度制限 -----
# ストレスは日単位で変わる状態量。遡り無制限だと何週間も前の高ストレス値が
# 「今夜の状態」として body_scan を選び続けてしまうため、必ず鮮度を制限する。


def test_latest_stress_ignores_stale_checkin(session):
    from datetime import date, timedelta

    from app.api.meditation import _latest_stress
    from app.models import SubjectiveCheckin

    stamp = datetime(2026, 7, 21, 12, 0)  # updated_at は NOT NULL

    target = date(2026, 7, 21)
    session.add(
        SubjectiveCheckin(date=target - timedelta(days=21), stress=5, updated_at=stamp)
    )
    session.commit()

    # 21 日前の値しか無い → 鮮度上限 1 日では「不明」扱いになる
    assert _latest_stress(session, target, 1) is None


def test_latest_stress_uses_fresh_checkin(session):
    from datetime import date, timedelta

    from app.api.meditation import _latest_stress
    from app.models import SubjectiveCheckin

    stamp = datetime(2026, 7, 21, 12, 0)  # updated_at は NOT NULL

    target = date(2026, 7, 21)
    session.add(
        SubjectiveCheckin(date=target - timedelta(days=21), stress=5, updated_at=stamp)
    )
    session.add(SubjectiveCheckin(date=target, stress=2, updated_at=stamp))
    session.commit()

    # 当日の値があればそれを使う (古い高ストレス値に引きずられない)
    assert _latest_stress(session, target, 1) == 2
