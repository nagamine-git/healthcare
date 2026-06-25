from __future__ import annotations

from app.scoring.garden.compute import bucket_level, compute_garden_day, weight_factor

CATALOG = [
    {"kind": "coding", "source": "github",
     "dimensions": ["ownership", "proactivity"], "base": 2.0, "evidence": "x"},
    {"kind": "meditation", "source": "manual",
     "dimensions": ["internal_locus"], "base": 1.2, "evidence": "x"},
]


def test_weight_factor_uses_max_gap_of_dimensions():
    gaps = {"ownership": 80.0, "proactivity": 20.0}
    assert weight_factor("coding", CATALOG, gaps, gamma=1.0) == 1.8


def test_weight_factor_fallback_when_all_gaps_none():
    gaps = {"ownership": None, "proactivity": None}
    assert weight_factor("coding", CATALOG, gaps, gamma=1.0) == 1.0


def test_weight_factor_missing_dimension_in_gaps_is_ignored():
    gaps = {"ownership": 50.0}
    assert weight_factor("coding", CATALOG, gaps, gamma=1.0) == 1.5


def test_bucket_level():
    th = [0.0, 1.0, 2.5, 4.5]
    assert bucket_level(0.0, th) == 0
    assert bucket_level(0.5, th) == 1
    assert bucket_level(1.0, th) == 1
    assert bucket_level(2.5, th) == 2
    assert bucket_level(3.0, th) == 3
    assert bucket_level(5.0, th) == 4


def test_compute_garden_day_sums_weighted_contributions():
    gaps = {"ownership": 80.0, "proactivity": 20.0, "internal_locus": 0.0}
    out = compute_garden_day(
        {"coding", "meditation"}, CATALOG, gaps, gamma=1.0, thresholds=[0.0, 1.0, 2.5, 4.5]
    )
    assert round(out["intensity"], 2) == 4.8
    assert out["contributions"]["coding"] == 3.6
    assert out["contributions"]["meditation"] == 1.2
    assert out["level"] == 4


def test_compute_garden_day_empty():
    out = compute_garden_day(set(), CATALOG, {}, gamma=1.0, thresholds=[0.0, 1.0, 2.5, 4.5])
    assert out == {"intensity": 0.0, "level": 0, "contributions": {}}


def test_compute_ignores_unknown_kind():
    out = compute_garden_day(
        {"unknown"}, CATALOG, {}, gamma=1.0, thresholds=[0.0, 1.0, 2.5, 4.5]
    )
    assert out["intensity"] == 0.0
