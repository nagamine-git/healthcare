from __future__ import annotations

import math


def test_circular_sd_small_when_clustered():
    from app.scoring.circadian import circular_sd_hours

    # 3:00 付近に集中 → SD は小さい
    sd = circular_sd_hours([3.0, 3.2, 2.8, 3.1, 2.9])
    assert sd is not None and sd < 0.3


def test_circular_sd_handles_midnight_wraparound():
    """23:50 と 0:10 を行き来する人は実際には ±0.2h しかブレていない。

    線形 SD なら平均 12h・SD≈12h と誤算するが、循環 SD なら小さい。
    """
    from app.scoring.circadian import circular_sd_hours

    hours = [23.83, 0.17, 23.83, 0.17, 0.0]  # 0時をまたぐ
    sd = circular_sd_hours(hours)
    assert sd is not None and sd < 0.5  # 線形だと ~12 になる


def test_circular_mean_wraparound():
    from app.scoring.circadian import circular_mean_hour

    m = circular_mean_hour([23.5, 0.5])  # 平均は 0:00 (12:00 ではない)
    assert m is not None
    # 0 か 24 付近
    assert min(abs(m - 0.0), abs(m - 24.0)) < 0.1


def test_circular_sd_none_when_insufficient():
    from app.scoring.circadian import circular_sd_hours

    assert circular_sd_hours([3.0]) is None
    assert circular_sd_hours([]) is None


def test_circular_sd_matches_linear_when_no_wrap():
    """0時をまたがない普通のケースでは線形 SD とほぼ一致する。"""
    import statistics

    from app.scoring.circadian import circular_sd_hours

    hours = [2.0, 3.0, 4.0, 2.5, 3.5]
    sd = circular_sd_hours(hours)
    linear = statistics.stdev(hours)
    # 循環 SD と線形 SD は定義が異なり完全一致はしないが、0時をまたがなければ近い
    assert sd is not None and math.isclose(sd, linear, rel_tol=0.2)
