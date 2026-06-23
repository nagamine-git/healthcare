from __future__ import annotations

from datetime import date

from app.scoring.activity_signal import DayEvidence, classify


def _ev(**kw) -> DayEvidence:
    base = dict(
        date=date(2026, 6, 20),
        steps=None,
        distance_m=None,
        workouts=(),
        outdoor_workout=False,
        exercise_min=None,
        has_hr=False,
        sources=(),
    )
    base.update(kw)
    return DayEvidence(**base)


def test_no_coverage_is_unknown_not_zero():
    r = classify(_ev())
    assert r["moved"] is None
    assert r["went_outside"] is None
    assert r["confidence"] == "none"


def test_enough_steps_moved():
    r = classify(_ev(steps=6000, sources=("hae",)))
    assert r["moved"] is True


def test_outdoor_workout_means_outside():
    r = classify(_ev(workouts=("walking",), outdoor_workout=True, sources=("garmin",)))
    assert r["moved"] is True
    assert r["went_outside"] is True


def test_indoor_only_moved_but_not_outside():
    r = classify(
        _ev(workouts=("strength_training",), outdoor_workout=False, steps=500, sources=("garmin",))
    )
    assert r["moved"] is True
    assert r["went_outside"] is False  # 屋内のみ → 外出ではない


def test_long_distance_implies_outside():
    r = classify(_ev(distance_m=2500, steps=4000, sources=("hae",)))
    assert r["went_outside"] is True


def test_confidence_high_with_garmin_continuous_hr():
    r = classify(_ev(steps=5000, has_hr=True, sources=("garmin",)))
    assert r["confidence"] == "high"


def test_confidence_medium_iphone_only():
    r = classify(_ev(steps=5000, sources=("hae",)))
    assert r["confidence"] == "medium"
