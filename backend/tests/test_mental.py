from __future__ import annotations

import pytest

from app.scoring.mental import (
    distress_achievement,
    score_screening,
    should_prompt,
)


def test_score_screening_sums_and_flags():
    r = score_screening(2, 2, 0, 1)  # phq2=4(陽性), gad2=1(陰性), phq4=5(軽度)
    assert r.phq2 == 4
    assert r.gad2 == 1
    assert r.phq4 == 5
    assert r.depression_positive is True
    assert r.anxiety_positive is False
    assert r.severity == "mild"


def test_score_screening_severity_bands():
    assert score_screening(0, 0, 0, 0).severity == "none"      # 0
    assert score_screening(1, 1, 0, 1).severity == "mild"      # 3
    assert score_screening(2, 2, 1, 1).severity == "moderate"  # 6
    assert score_screening(3, 3, 2, 1).severity == "severe"    # 9


def test_score_screening_rejects_out_of_range():
    with pytest.raises(ValueError):
        score_screening(4, 0, 0, 0)
    with pytest.raises(ValueError):
        score_screening(0, -1, 0, 0)


def test_distress_achievement_inverts_phq4():
    assert distress_achievement(0) == 100.0
    assert distress_achievement(12) == 0.0
    assert distress_achievement(6) == 50.0
    assert distress_achievement(None) is None  # 未実施=未計測


def test_should_prompt_first_time():
    out = should_prompt(days_since_last=None, bad_signal=False)
    assert out["due"] is True
    assert "はじめて" in out["reason"]


def test_should_prompt_bad_signal_shortens_window():
    # 不調サインあり + 最終から3日 → 促す (定期14日を待たない)
    assert should_prompt(days_since_last=3, bad_signal=True)["due"] is True
    # ただし直近(1日)に実施済みなら促さない (連投防止)
    assert should_prompt(days_since_last=1, bad_signal=True)["due"] is False


def test_should_prompt_cadence_when_calm():
    assert should_prompt(days_since_last=14, bad_signal=False)["due"] is True
    assert should_prompt(days_since_last=7, bad_signal=False)["due"] is False
