from __future__ import annotations

from datetime import datetime

from app.scoring.fallback_advice import build_fallback_advice


def test_empty_input_returns_safe_default():
    out = build_fallback_advice(now=datetime(2026, 5, 23, 10, 0))
    assert "headline" in out
    assert "actions" in out
    assert isinstance(out["actions"], list)
    assert len(out["actions"]) == 0
    assert "ルールベース" in out["rationale"]


def test_critical_alert_becomes_action():
    alerts = [
        {
            "code": "chronic_sleep_deficit",
            "severity": "critical",
            "title": "3 日中 2 夜が 5 時間未満",
            "detail": "認知低下リスク",
            "action": "今日は重要判断を避け、20 分ナップ",
        }
    ]
    out = build_fallback_advice(now=datetime(2026, 5, 23, 10, 0), alerts=alerts)
    assert len(out["actions"]) >= 1
    a0 = out["actions"][0]
    assert a0["priority"] == "critical"
    assert "ナップ" in a0["title"] or "判断" in a0["title"]
    # 14-15 時のナップ提案
    assert a0["time_jst"].startswith("14:")


def test_max_3_actions():
    """alerts と caffeine と focus を全部渡しても 3 件まで。"""
    alerts = [
        {
            "code": "chronic_sleep_deficit",
            "severity": "critical",
            "title": "A",
            "detail": "x",
            "action": "対応A",
        },
        {
            "code": "hrv_chronic_decline",
            "severity": "warning",
            "title": "B",
            "detail": "y",
            "action": "対応B",
        },
        {
            "code": "moh_risk_mid",
            "severity": "warning",
            "title": "C",
            "detail": "z",
            "action": "対応C",
        },
    ]
    caffeine = {
        "available": True,
        "recommended_mg": 60,
        "instant_coffee_g": 1.0,
        "reason": "OK",
    }
    focus = {
        "level": "high",
        "peak_windows": [{"start": "14:00", "end": "16:00", "avg_score": 80}],
    }
    out = build_fallback_advice(
        now=datetime(2026, 5, 23, 9, 0),
        alerts=alerts,
        caffeine=caffeine,
        focus=focus,
    )
    assert len(out["actions"]) == 3


def test_caffeine_recommendation_added_when_no_alerts():
    out = build_fallback_advice(
        now=datetime(2026, 5, 23, 9, 0),
        caffeine={
            "available": True,
            "recommended_mg": 60,
            "instant_coffee_g": 1.0,
            "reason": "目標通り",
        },
    )
    assert any("コーヒー" in a["title"] for a in out["actions"])


def test_focus_peak_window_added():
    out = build_fallback_advice(
        now=datetime(2026, 5, 23, 9, 0),
        focus={
            "level": "high",
            "peak_windows": [{"start": "14:00", "end": "16:00", "avg_score": 80}],
        },
    )
    assert any("ディープワーク" in a["title"] for a in out["actions"])


def test_pressure_warning_adds_recovery_action():
    out = build_fallback_advice(
        now=datetime(2026, 5, 23, 9, 0),
        pressure={
            "risk_level": "warning",
            "risk_reason": "気圧降下",
        },
    )
    assert any(a["category"] == "recovery" for a in out["actions"])


def test_headline_reflects_critical_alert():
    out = build_fallback_advice(
        now=datetime(2026, 5, 23, 9, 0),
        alerts=[
            {
                "code": "chronic_sleep_deficit",
                "severity": "critical",
                "title": "3 日中 2 夜が 5 時間未満",
                "detail": "",
                "action": "ナップ",
            }
        ],
    )
    assert "3 日" in out["headline"] or "5 時間" in out["headline"]


def test_payload_schema_compatible_with_llm():
    """LLM の SUBMIT_ADVICE_TOOL と同じ field を返すか。"""
    out = build_fallback_advice(now=datetime(2026, 5, 23, 9, 0))
    assert set(out.keys()) >= {"headline", "focus", "actions", "rationale"}
    for a in out["actions"]:
        assert "time_jst" in a
        assert "title" in a
        assert "duration_min" in a
        assert "category" in a
        assert "priority" in a
