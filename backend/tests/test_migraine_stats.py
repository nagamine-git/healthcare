from __future__ import annotations

import math


def test_permutation_pvalue_separates_clear_difference():
    from app.scoring.migraine_stats import permutation_test

    # ケースが明確に高い → 小さい p
    case = [9.0, 8.0, 10.0, 9.5]
    control = [1.0, 2.0, 1.5, 0.5, 2.0, 1.0]
    p, diff = permutation_test(case, control, iterations=2000)
    assert diff > 5.0
    assert p < 0.05


def test_permutation_pvalue_large_when_no_difference():
    from app.scoring.migraine_stats import permutation_test

    case = [5.0, 4.0, 6.0]
    control = [5.0, 6.0, 4.0, 5.0, 5.5, 4.5]
    p, _ = permutation_test(case, control, iterations=2000)
    assert p > 0.2


def test_permutation_deterministic():
    """同じ入力なら同じ p (シード固定/決定的)。"""
    from app.scoring.migraine_stats import permutation_test

    case = [7.0, 8.0, 6.5]
    control = [3.0, 4.0, 2.0, 5.0]
    p1, _ = permutation_test(case, control, iterations=1000)
    p2, _ = permutation_test(case, control, iterations=1000)
    assert p1 == p2


def test_permutation_insufficient_returns_none():
    from app.scoring.migraine_stats import permutation_test

    p, diff = permutation_test([5.0], [], iterations=100)
    assert p is None and diff is None


def test_benjamini_hochberg_orders_and_thresholds():
    from app.scoring.migraine_stats import benjamini_hochberg

    # 既知の p 値。BH q 値は単調で、元 p 以上。
    ps = [0.01, 0.04, 0.03, 0.20]
    qs = benjamini_hochberg(ps)
    assert len(qs) == 4
    for p, q in zip(ps, qs, strict=True):
        assert q >= p - 1e-9
    # 最小 p (0.01, n=4) → q = 0.01*4/1 = 0.04
    assert math.isclose(qs[0], 0.04, abs_tol=1e-9)


def test_onset_profile_buckets_and_peak():
    from datetime import datetime

    from app.scoring.migraine_stats import onset_profile

    # 発症時刻 (JST naive datetime) 14時台に集中
    onsets = [
        datetime(2026, 6, 1, 14, 0),
        datetime(2026, 6, 2, 15, 30),
        datetime(2026, 6, 3, 13, 0),
        datetime(2026, 6, 4, 9, 0),
    ]
    prof = onset_profile(onsets)
    assert prof["peak_bucket"] == "昼〜午後"  # 11-17
    bucket = {b["label"]: b["count"] for b in prof["buckets"]}
    assert bucket["昼〜午後"] == 3
    assert bucket["早朝〜午前"] == 1
    assert 12.0 <= prof["mean_hour"] <= 15.0


def test_onset_profile_empty():
    from app.scoring.migraine_stats import onset_profile

    prof = onset_profile([])
    assert prof["peak_bucket"] is None
    assert all(b["count"] == 0 for b in prof["buckets"])
