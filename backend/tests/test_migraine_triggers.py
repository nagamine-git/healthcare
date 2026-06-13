from __future__ import annotations

from datetime import date, datetime, timedelta

from app.db import session_scope
from app.models import CaffeineIntake, MetricSample, MigraineEpisode

# DB は UTC naive。JST 15:00 = UTC 06:00。
JST_AFTERNOON_UTC_HOUR = 6


def _pressure(s, ts: datetime, hpa: float):
    s.add(MetricSample(source="open-meteo", metric_key="surface_pressure_hpa", ts=ts, value=hpa))


def test_accumulating_below_min_episodes(db_engine):
    from app.scoring.migraine_triggers import analyze_triggers

    today = date(2026, 6, 8)
    with session_scope() as s:
        for i in range(3):
            d = today - timedelta(days=i * 2)
            s.add(MigraineEpisode(
                started_at=datetime.combine(d, datetime.min.time()).replace(hour=JST_AFTERNOON_UTC_HOUR)))

    out = analyze_triggers(today, min_episodes=10)
    # 3 例は permutation が成立しない最小未満 → accumulating (4 例で分析開始)
    assert out["status"] == "accumulating"
    assert out["episode_count"] == 3
    assert out["remaining"] == 1
    assert out["reliability"] == "very_low"
    assert out["onset_profile"]["peak_bucket"] == "昼〜午後"  # JST 15:00
    assert out["factors"] == []


def test_detects_pressure_swing_factor(db_engine):
    """頭痛の直前 24h に気圧が大きく動き、非頭痛日は安定 → pressure_drop が有意。"""
    from app.scoring.migraine_triggers import analyze_triggers

    today = date(2026, 6, 30)
    with session_scope() as s:
        # 全日、安定した気圧 (1013) を 3h おきに敷く
        for i in range(31):
            d = today - timedelta(days=i)
            for h in range(0, 24, 3):
                _pressure(s, datetime.combine(d, datetime.min.time()).replace(hour=h), 1013.0)
        # 頭痛 12 件: 発症 (UTC06=JST15) の直前に急降下を入れる
        for i in range(12):
            d = today - timedelta(days=i * 2)
            onset = datetime.combine(d, datetime.min.time()).replace(hour=JST_AFTERNOON_UTC_HOUR)
            s.add(MigraineEpisode(started_at=onset))
            # 3h グリッドと衝突しないオフセットで急降下を挿入
            _pressure(s, onset - timedelta(hours=5), 1006.0)
            _pressure(s, onset - timedelta(hours=2), 1000.0)
            _pressure(s, onset - timedelta(hours=1), 998.0)

    out = analyze_triggers(today, min_episodes=10)
    assert "pressure_drop" in out["tested"]
    pf = next((f for f in out["factors"] if f["key"] == "pressure_drop"), None)
    assert pf is not None, f"pressure_drop should be significant: {out['status']} {out['factors']}"
    assert pf["direction"] == "誘発"
    assert pf["case_mean"] > pf["control_mean"]
    assert pf["tier"] == "strong"
    assert out["status"] == "analyzed"
    assert out["reliability"] == "medium"  # 12 例


def test_caffeine_single_factor_not_mirror(db_engine):
    """カフェインは離脱/過多の鏡像2行ではなく、観測方向で1因子に統合される。"""
    from app.scoring.migraine_triggers import analyze_triggers

    today = date(2026, 6, 30)
    with session_scope() as s:
        def _caf(ts, mg):
            return CaffeineIntake(ts=ts, source="manual", amount=mg, unit="mg", mg=mg)
        # 全日に少量のベースライン摂取 (50mg/日) を敷く
        for i in range(31):
            d = today - timedelta(days=i)
            s.add(_caf(datetime.combine(d, datetime.min.time()).replace(hour=0), 50.0))
        # 頭痛 12 件: 発症直前に大量カフェイン (過多) を入れる
        for i in range(12):
            d = today - timedelta(days=i * 2)
            onset = datetime.combine(d, datetime.min.time()).replace(hour=JST_AFTERNOON_UTC_HOUR)
            s.add(MigraineEpisode(started_at=onset))
            s.add(_caf(onset - timedelta(hours=2), 200.0))

    out = analyze_triggers(today, min_episodes=10)
    # caffeine_withdrawal / caffeine_excess の2キーは存在しない
    assert "caffeine_withdrawal" not in out["tested"]
    assert "caffeine_excess" not in out["tested"]
    caf = [f for f in out["factors"] if f["key"] == "caffeine"]
    assert len(caf) == 1  # 鏡像で2行出ない
    # 頭痛日に多い → 過多・誘発
    assert caf[0]["label"] == "カフェイン過多"
    assert caf[0]["direction"] == "誘発"


def test_no_significant_factor_when_flat(db_engine):
    """気圧が常に一定 → どの要因も有意でない。"""
    from app.scoring.migraine_triggers import analyze_triggers

    today = date(2026, 6, 30)
    with session_scope() as s:
        for i in range(31):
            d = today - timedelta(days=i)
            for h in range(0, 24, 3):
                _pressure(s, datetime.combine(d, datetime.min.time()).replace(hour=h), 1013.0)
        for i in range(12):
            d = today - timedelta(days=i * 2)
            s.add(MigraineEpisode(
                started_at=datetime.combine(d, datetime.min.time()).replace(hour=JST_AFTERNOON_UTC_HOUR)))

    out = analyze_triggers(today, min_episodes=10)
    # 全要因を返すが、平坦なので強い (strong) 判定は出ない
    assert out["status"] in ("analyzed", "no_data")
    assert not any(f["tier"] == "strong" for f in out["factors"])
    assert out["episode_count"] == 12
