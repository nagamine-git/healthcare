from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.db import session_scope
from app.models import WeightSample
from app.scoring.body_trend import smoothed_body


def _add(session, days_ago: float, w: float, bf: float | None = None):
    ts = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days_ago)
    session.add(WeightSample(ts=ts, weight_kg=w, body_fat_pct=bf, source="test"))


def test_smoothed_weights_recent_more(db_engine):
    with session_scope() as s:
        _add(s, 0, 55.0, 16.0)   # 直近
        _add(s, 7, 57.0, 18.0)
        _add(s, 14, 59.0, 20.0)
    est = smoothed_body(half_life_days=14.0)
    # 直近を重く加重 → 単純平均(57)より直近(55)寄り
    assert est.weight_kg < 57.0
    assert est.raw_weight_kg == 55.0  # 生値は直近1回
    assert est.n == 3
    # 体脂肪も同様に直近寄り
    assert est.body_fat_pct < 18.0


def test_smoothed_drops_outlier(db_engine):
    with session_scope() as s:
        _add(s, 0, 55.0)
        _add(s, 1, 55.2)
        _add(s, 2, 80.0)  # 明らかな誤測 (中央値から +25kg)
    est = smoothed_body()
    assert est.weight_kg < 60.0  # 誤測は除外される
    assert est.n == 2


def test_smoothed_empty(db_engine):
    est = smoothed_body()
    assert est.weight_kg is None
    assert est.n == 0
