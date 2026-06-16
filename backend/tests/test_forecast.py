from __future__ import annotations

from datetime import datetime, timedelta

from app.db import session_scope
from app.models import BodyBattery
from app.scoring import forecast as fc


def test_forecast_shape_no_data(db_engine, monkeypatch):
    # 気圧予報を空にして migraine=None、BBなしで energy=None を確認
    monkeypatch.setattr(fc, "get_pressure_hourly", lambda **k: [])
    out = fc.forecast(now_jst=datetime(2026, 6, 14, 10, 0))
    assert out["migraine"] is None
    assert out["energy_today"] is None
    assert "tomorrow" in out


def test_migraine_forecast_flags_pressure_swing(db_engine, monkeypatch):
    """48h予報に大きな気圧変動 → リスク高のバケットが出る。"""
    now = datetime(2026, 6, 14, 10, 0)
    # 未来に向け気圧が急降下する予報を合成 (JST naive)
    series = []
    base = now - timedelta(hours=24)
    for i in range(72):
        ts = base + timedelta(hours=i)
        # 最初は1015で安定、24h以降に1000まで急降下
        hpa = 1015.0 if i < 36 else 1000.0
        series.append((ts, hpa))
    monkeypatch.setattr(fc, "get_pressure_hourly", lambda **k: series)
    out = fc.forecast(now_jst=now)
    assert out["migraine"] is not None
    risks = {b["risk"] for b in out["migraine"]["buckets"]}
    assert "high" in risks or "elevated" in risks
    assert out["migraine"]["peak"]["swing_hpa"] >= 5


def test_migraine_forecast_suppressed_when_swing_low(db_engine, monkeypatch):
    """気圧変動が日内変動レベル (~3hPa) なら予報を出さない (狼少年回避)。"""
    now = datetime(2026, 6, 14, 10, 0)
    base = now - timedelta(hours=24)
    # 1013〜1016 を緩く往復 = 24h ウィンドウの変動幅 ~3hPa → 全バケット「低」
    series = [(base + timedelta(hours=i), 1013.0 + (i % 4)) for i in range(72)]
    monkeypatch.setattr(fc, "get_pressure_hourly", lambda **k: series)
    out = fc.forecast(now_jst=now)
    assert out["migraine"] is None


def test_energy_projection_from_bb_slope(db_engine, monkeypatch):
    monkeypatch.setattr(fc, "get_pressure_hourly", lambda **k: [])
    now = datetime(2026, 6, 14, 15, 0)
    now_utc = now - timedelta(hours=9)
    with session_scope() as s:
        # 直近4hで 80→50 に消耗 (slope ~ -7.5/h)
        for i, v in enumerate([80, 72, 64, 56, 50]):
            s.add(BodyBattery(ts=now_utc - timedelta(hours=4) + timedelta(hours=i), value=float(v)))
    out = fc.forecast(now_jst=now)
    e = out["energy_today"]
    assert e is not None
    assert e["slope_per_h"] < 0
    assert e["empty_eta"] is not None  # 枯渇予測時刻が出る
