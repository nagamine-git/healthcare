from __future__ import annotations

from datetime import date

from app.scoring.becoming.trajectory import dimension_slope, project


def test_dimension_slope_linear():
    # 10日で 10 上昇 → 1.0/day
    pts = [(date(2026, 6, 1), 50.0), (date(2026, 6, 11), 60.0)]
    assert dimension_slope(pts) == 1.0


def test_dimension_slope_none_when_insufficient():
    assert dimension_slope([(date(2026, 6, 1), 50.0)]) is None


def _snap(d, dims):
    return {"date": d, "dim_estimates": dims}


def test_project_eta_and_bottleneck():
    # ownership は遅く(0.5/day, gap大)、proactivity は速い(2/day)
    snaps = [
        _snap(date(2026, 6, 1), {"ownership": 50.0, "proactivity": 60.0}),
        _snap(date(2026, 6, 11), {"ownership": 55.0, "proactivity": 80.0}),
    ]
    targets = {"ownership": 90.0, "proactivity": 90.0}
    weights = {"ownership": 2.5, "proactivity": 1.0}
    out = project(snaps, targets, weights, window_days=90, min_snapshots=2)
    # ownership: (90-55)/0.5 = 70日、proactivity: (90-80)/2 = 5日 → ボトルネックは ownership
    assert out["bottleneck_dimension"] == "ownership"
    assert out["eta_days"] == 70
    assert out["confidence"] == "medium"


def test_project_low_confidence_when_few_snapshots():
    snaps = [
        _snap(date(2026, 6, 1), {"ownership": 50.0}),
        _snap(date(2026, 6, 11), {"ownership": 55.0}),
    ]
    out = project(snaps, {"ownership": 90.0}, {"ownership": 2.5}, window_days=90, min_snapshots=14)
    assert out["confidence"] == "low"


def test_project_eta_none_when_no_progress():
    # 横ばい → 到達不能 → eta None
    snaps = [
        _snap(date(2026, 6, 1), {"ownership": 55.0}),
        _snap(date(2026, 6, 11), {"ownership": 55.0}),
    ]
    out = project(snaps, {"ownership": 90.0}, {"ownership": 2.5}, window_days=90, min_snapshots=2)
    assert out["eta_days"] is None
    assert out["bottleneck_dimension"] == "ownership"
