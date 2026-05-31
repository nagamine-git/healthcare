from __future__ import annotations

from datetime import date, timedelta

from app.scoring import trends


def _series(values, start=date(2026, 5, 1)):
    return [(start + timedelta(days=i), v) for i, v in enumerate(values)]


def test_compute_trend_improving():
    # 単調増加 → improving, 前日比 +2
    t = trends.compute_trend(_series([60, 62, 64, 66, 68, 70, 72, 74]))
    assert t["current"] == 74
    assert t["prev_day_change"] == 2
    assert t["direction"] == "improving"
    assert t["week_over_week"]["delta"] > 0


def test_compute_trend_declining():
    t = trends.compute_trend(_series([80, 78, 76, 74, 72, 70, 68, 66]))
    assert t["direction"] == "declining"
    assert t["prev_day_change"] == -2


def test_compute_trend_stable():
    t = trends.compute_trend(_series([70, 70, 70, 70, 70, 70, 70]))
    assert t["direction"] == "stable"


def test_compute_trend_too_few_points():
    t = trends.compute_trend(_series([70]))
    assert t["direction"] is None
    assert t["prev_day_change"] is None
    assert t["week_over_week"] is None
    assert t["current"] == 70


def test_compute_trend_higher_is_better_false_inverts():
    # 増加系列でも higher_is_better=False なら declining
    t = trends.compute_trend(_series([60, 62, 64, 66, 68, 70, 72]), higher_is_better=False)
    assert t["direction"] == "declining"


def test_compute_trend_skips_none():
    t = trends.compute_trend(_series([60, None, 64, None, 68, 70, 72, 74]))
    # None を除外して計算できる
    assert t["current"] == 74
    assert t["direction"] == "improving"


def test_weekly_average_groups_by_monday():
    # 2026-05-04 は月曜
    s = _series([10, 20, 30, 40, 50, 60, 70], start=date(2026, 5, 4))  # 月〜日
    s += _series([100], start=date(2026, 5, 11))  # 翌週月曜
    out = trends.weekly_average(s)
    assert out[0] == {"date": "2026-05-04", "value": 40.0}  # (10..70)/7
    assert out[1] == {"date": "2026-05-11", "value": 100.0}


def test_series_by_column_and_build_metrics():
    # rows: (date, total, sleep_sub, hrv_sub, bb_sub, load_sub, weight_sub, body_fat_sub)
    rows = []
    for i in range(8):
        d = date(2026, 5, 1) + timedelta(days=i)
        rows.append((d, 60 + i * 2, 50 + i, None, 70, 80, 75, 90))
    by_col = trends.series_by_column(rows)
    assert len(by_col["total"]) == 8
    assert len(by_col["hrv_sub"]) == 0  # 4 番目 (hrv_sub) は全て None

    metrics = trends.build_metrics(by_col, granularity="daily")
    assert metrics["total"]["label"] == "総合スコア"
    assert metrics["total"]["direction"] == "improving"
    assert metrics["total"]["higher_is_better"] is True
    assert len(metrics["total"]["series"]) == 8
    # 全 None の指標 (hrv) は series 空 / direction None
    assert metrics["hrv"]["series"] == []
    assert metrics["hrv"]["direction"] is None
