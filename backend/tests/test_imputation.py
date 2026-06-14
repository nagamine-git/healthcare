from __future__ import annotations

from datetime import date, datetime, timedelta

from app.db import session_scope
from app.models import AlcoholIntake, HrvDaily, SleepSession
from app.scoring import imputation as imp


def _seed_sleep(s, d: date, score: float):
    s.add(SleepSession(date=d, total_min=420, sleep_score=score, source="garmin"))


def test_missing_detection(db_engine):
    target = date(2026, 6, 14)
    with session_scope() as s:
        _seed_sleep(s, target - timedelta(days=1), 80)  # 過去のみ
    hist = imp._load_history(target)
    miss = imp.missing_metrics(target, hist)
    assert "sleep_score" in miss  # 当日は未実測
    assert "hrv" in miss


def test_present_metric_not_imputed(db_engine):
    target = date(2026, 6, 14)
    with session_scope() as s:
        for i in range(20):
            _seed_sleep(s, target - timedelta(days=i), 70 + (i % 5))
    out = imp.impute_day(target, only_missing=True)
    # 当日 sleep が実測済みなら補完対象に含めない
    assert "sleep_score" not in out


def test_knn_uses_alcohol_signal(db_engine):
    """飲酒した夜は HRV が低い履歴 → 飲酒した当日の推定 HRV も低い。"""
    target = date(2026, 6, 14)
    with session_scope() as s:
        # 60日: 飲酒(前夜)した日は HRV 30、しない日は HRV 60
        for i in range(1, 61):
            d = target - timedelta(days=i)
            drank = i % 2 == 0
            s.add(HrvDaily(date=d, last_night_avg=30.0 if drank else 60.0, weekly_avg=45.0))
            if drank:
                # 前夜 (d-1 の夜) に飲酒
                s.add(AlcoholIntake(ts=datetime.combine(d - timedelta(days=1), datetime.min.time())
                                    .replace(hour=12), source="beer", grams=20.0))
        # 当日の前夜に飲酒あり
        s.add(AlcoholIntake(ts=datetime.combine(target - timedelta(days=1), datetime.min.time())
                            .replace(hour=12), source="beer", grams=20.0))
    hist = imp._load_history(target)
    res = imp.impute_metric("hrv", target, hist)
    assert res is not None
    assert res.method == "knn"
    assert res.value < 45  # 飲酒側 (~30) に寄る
    assert "前夜の飲酒" in res.drivers
    assert res.low is not None and res.high is not None


def test_fallback_to_baseline_when_sparse(db_engine):
    target = date(2026, 6, 14)
    with session_scope() as s:
        # 候補2日のみ → MIN_NEIGHBORS 未満で baseline
        s.add(HrvDaily(date=target - timedelta(days=2), last_night_avg=50.0, weekly_avg=50.0))
        s.add(HrvDaily(date=target - timedelta(days=3), last_night_avg=54.0, weekly_avg=50.0))
    hist = imp._load_history(target)
    res = imp.impute_metric("hrv", target, hist)
    assert res is not None
    assert res.method == "baseline"
    assert res.confidence == "low"
    assert 50 <= res.value <= 54


def test_no_history_returns_none(db_engine):
    target = date(2026, 6, 14)
    hist = imp._load_history(target)
    assert imp.impute_metric("hrv", target, hist) is None


def test_moon_illumination_range(db_engine):
    for d in (date(2026, 1, 1), date(2026, 6, 14), date(2026, 12, 31)):
        v = imp._moon_illumination(d)
        assert 0.0 <= v <= 1.0
