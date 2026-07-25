from __future__ import annotations

from datetime import date, datetime, timedelta

from app.db import session_scope
from app.models import (
    CaffeineIntake,
    MetricSample,
    MigraineEpisode,
    SleepSession,
    SubjectiveCheckin,
    Workout,
)

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


def test_detects_subjective_stress_factor(db_engine):
    """発症前日〜当日の主観ストレスが高い → subjective_stress が有意。"""
    from app.scoring.migraine_triggers import analyze_triggers

    today = date(2026, 6, 30)
    # episode_days 同士が重ならないよう 5 日間隔で配置 (前日〜当日窓が他の頭痛日と衝突しない)
    episode_days = {today - timedelta(days=i * 5) for i in range(12)}
    with session_scope() as s:
        # 70日分のベースライン記録。頭痛当日だけ主観ストレスが高い (5)、他は低い (1)
        for i in range(70):
            d = today - timedelta(days=i)
            stress = 5 if d in episode_days else 1
            s.add(SubjectiveCheckin(
                date=d, stress=stress,
                updated_at=datetime.combine(d, datetime.min.time())))
        for d in episode_days:
            onset = datetime.combine(d, datetime.min.time()).replace(hour=JST_AFTERNOON_UTC_HOUR)
            s.add(MigraineEpisode(started_at=onset))

    out = analyze_triggers(today, min_episodes=10)
    assert "subjective_stress" in out["tested"]
    sf = next((f for f in out["factors"] if f["key"] == "subjective_stress"), None)
    assert sf is not None, f"subjective_stress should be significant: {out['status']} {out['factors']}"
    assert sf["direction"] == "誘発"
    assert sf["case_mean"] > sf["control_mean"]


def test_detects_exercise_load_factor(db_engine):
    """発症の前日 (24-48h前) に高い運動負荷 → exercise_load が有意 (誘発方向)。"""
    from app.scoring.migraine_triggers import analyze_triggers

    today = date(2026, 6, 30)
    with session_scope() as s:
        for i in range(12):
            d = today - timedelta(days=i * 2)
            onset = datetime.combine(d, datetime.min.time()).replace(hour=JST_AFTERNOON_UTC_HOUR)
            s.add(MigraineEpisode(started_at=onset))
            # 発症の24-48h前 (前日) に高負荷ワークアウトを 1 件だけ入れる
            s.add(Workout(
                id=f"wk-{i}", source="garmin",
                start=onset - timedelta(hours=30), training_load=120.0))

    out = analyze_triggers(today, min_episodes=10)
    assert "exercise_load" in out["tested"]
    ef = next((f for f in out["factors"] if f["key"] == "exercise_load"), None)
    assert ef is not None, f"exercise_load should be significant: {out['status']} {out['factors']}"
    assert ef["direction"] == "誘発"
    assert ef["case_mean"] > ef["control_mean"]


def test_sleep_deviation_catches_oversleep(db_engine):
    """sleep_short は片側 (不足) だけでなく寝過ぎ (過多) も両側乖離として拾う。"""
    from app.scoring.migraine_triggers import analyze_triggers

    today = date(2026, 6, 30)
    episode_days = {today - timedelta(days=i * 2) for i in range(12)}
    with session_scope() as s:
        # 頭痛日だけ 600 分 (8h 目標より2h の寝過ぎ)、他は目標通り 480 分
        for i in range(31):
            d = today - timedelta(days=i)
            total = 600 if d in episode_days else 480
            s.add(SleepSession(date=d, source="garmin", total_min=total))
        for d in episode_days:
            onset = datetime.combine(d, datetime.min.time()).replace(hour=JST_AFTERNOON_UTC_HOUR)
            s.add(MigraineEpisode(started_at=onset))

    out = analyze_triggers(today, min_episodes=10)
    assert "sleep_short" in out["tested"]
    sf = next((f for f in out["factors"] if f["key"] == "sleep_short"), None)
    assert sf is not None, f"sleep_short should be significant: {out['status']} {out['factors']}"
    assert sf["direction"] == "誘発"
    assert sf["case_mean"] > sf["control_mean"]
    assert sf["case_mean"] > 0  # 片側 (480-total) なら寝過ぎは負値になり検出できなかった


def test_detects_sleep_breath_disruption_factor(db_engine):
    """頭痛日の前夜だけ呼吸の乱れ (severity) が高い → sleep_breath_disruption が有意。"""
    from app.scoring.migraine_triggers import analyze_triggers

    today = date(2026, 6, 30)
    episode_days = {today - timedelta(days=i * 2) for i in range(12)}
    with session_scope() as s:
        # 31日分、頭痛日は HIGH(2.0)、他は LOW(0.0) の breathingDisruptionSeverity
        for i in range(31):
            d = today - timedelta(days=i)
            severity = 2.0 if d in episode_days else 0.0
            ts = datetime.combine(d, datetime.min.time()).replace(hour=7)
            s.add(MetricSample(
                source="garmin", metric_key="sleep_breath_disruption", ts=ts, value=severity))
        for d in episode_days:
            onset = datetime.combine(d, datetime.min.time()).replace(hour=JST_AFTERNOON_UTC_HOUR)
            s.add(MigraineEpisode(started_at=onset))

    out = analyze_triggers(today, min_episodes=10)
    assert "sleep_breath_disruption" in out["tested"]
    bf = next((f for f in out["factors"] if f["key"] == "sleep_breath_disruption"), None)
    assert bf is not None, f"sleep_breath_disruption should be significant: {out['status']} {out['factors']}"
    assert bf["direction"] == "誘発"
    assert bf["case_mean"] > bf["control_mean"]


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
