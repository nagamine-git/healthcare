from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.integrations.gcal import parse_advice_actions

JST = ZoneInfo("Asia/Tokyo")


SAMPLE_COMMENT = """\
【今日のフォーカス】
睡眠は良好ですが Body Battery が低めです。

【推奨アクション】
- [11:30] 軽食＋水分補給 (10分)
- [13:00] ラッキング Z2 (25分、会話できるペース、時速 8 km/h 程度)
- [16:00] 軽い上半身モビリティ (10分)

【根拠】
Body Battery 18 を引用。
"""


def test_parse_advice_actions_extracts_three():
    today = datetime(2026, 5, 6, 9, 0, tzinfo=JST)
    actions = parse_advice_actions(SAMPLE_COMMENT, today)
    assert len(actions) == 3

    a0 = actions[0]
    assert a0["start"].hour == 11 and a0["start"].minute == 30
    assert a0["duration_min"] == 10
    assert "軽食" in a0["title"]

    a1 = actions[1]
    assert a1["start"].hour == 13
    assert a1["duration_min"] == 25

    a2 = actions[2]
    assert a2["duration_min"] == 10


def test_parse_advice_actions_handles_no_block():
    today = datetime(2026, 5, 6, 9, 0, tzinfo=JST)
    actions = parse_advice_actions("ただのテキスト", today)
    assert actions == []


def test_parse_advice_actions_default_duration_30():
    text = """【推奨アクション】
- [10:00] 散歩
"""
    today = datetime(2026, 5, 6, 9, 0, tzinfo=JST)
    actions = parse_advice_actions(text, today)
    assert len(actions) == 1
    assert actions[0]["duration_min"] == 30


def test_parse_advice_actions_full_width_brackets():
    text = """【推奨アクション】
- [09:30] ストレッチ（所要 15 分、軽い強度）
"""
    today = datetime(2026, 5, 6, 8, 0, tzinfo=JST)
    actions = parse_advice_actions(text, today)
    assert len(actions) == 1
    assert actions[0]["duration_min"] == 15
    assert "ストレッチ" in actions[0]["title"]
