from __future__ import annotations

from app.scoring.becoming.metrics import loop_week


def _snap(condition=None, intensity=0.0, focus=0.0, proximity=None):
    return {
        "condition": condition,
        "garden_intensity": intensity,
        "garden_focus": focus,
        "overall_proximity": proximity,
    }


def test_capacity_utilization_among_good_days():
    snaps = [
        _snap(condition=80, intensity=2.0),  # 良好日・行動あり
        _snap(condition=85, intensity=0.0),  # 良好日・行動なし
        _snap(condition=50, intensity=3.0),  # 良好日でない(無視)
    ]
    out = loop_week(snaps, good_threshold=70.0)
    assert out["capacity_utilization"] == 0.5  # 良好2日中1日行動


def test_capacity_utilization_none_when_no_good_days():
    out = loop_week([_snap(condition=40, intensity=2.0)], good_threshold=70.0)
    assert out["capacity_utilization"] is None


def test_action_alignment_mean_focus_over_active_days():
    snaps = [_snap(intensity=2.0, focus=0.8), _snap(intensity=1.0, focus=0.4), _snap(intensity=0.0, focus=0.9)]
    out = loop_week(snaps, good_threshold=70.0)
    assert out["action_alignment"] == 0.6  # (0.8+0.4)/2、活動なし日は除外


def test_identity_movement_delta_proximity():
    snaps = [_snap(proximity=40.0), _snap(proximity=None), _snap(proximity=46.0)]
    out = loop_week(snaps, good_threshold=70.0)
    assert out["identity_movement"] == 6.0


def test_diagnosis_wasted_capacity():
    # 良好日が多いのに行動が少ない
    snaps = [_snap(condition=80, intensity=0.0), _snap(condition=82, intensity=0.0),
             _snap(condition=78, intensity=2.0, focus=0.7)]
    out = loop_week(snaps, good_threshold=70.0)
    assert out["diagnosis"] == "wasted_capacity"


def test_diagnosis_spinning():
    # 整合は高いのに前進していない
    snaps = [_snap(condition=80, intensity=2.0, focus=0.9, proximity=50.0),
             _snap(condition=80, intensity=2.0, focus=0.9, proximity=49.0)]
    out = loop_week(snaps, good_threshold=70.0)
    assert out["diagnosis"] == "spinning"


def test_diagnosis_flywheel_turning():
    snaps = [_snap(condition=80, intensity=2.0, focus=0.8, proximity=40.0),
             _snap(condition=82, intensity=2.0, focus=0.8, proximity=44.0)]
    out = loop_week(snaps, good_threshold=70.0)
    assert out["diagnosis"] == "flywheel_turning"
