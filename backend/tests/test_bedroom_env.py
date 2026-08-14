"""寝室環境 (SwitchBot) の取得と記録。"""

from __future__ import annotations

from app.integrations import switchbot


def _fake_client(payload):
    class _R:
        def raise_for_status(self): pass
        def json(self): return payload

    class _C:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, *a, **kw): return _R()
    return _C


def _configure(monkeypatch):
    from app.config import Settings

    s = Settings(switchbot_token="t" * 96, switchbot_secret="s" * 32,
                 switchbot_bedroom_device_id="B0E9FE585E3A")
    monkeypatch.setattr(switchbot, "get_settings", lambda: s)


def test_signature_uses_milliseconds(monkeypatch):
    """⚠️ t は**ミリ秒**。秒で送ると SwitchBot は 401 を返す。"""
    _configure(monkeypatch)
    h = switchbot._headers("t" * 96, "s" * 32)
    assert len(h["t"]) == 13, "秒 (10桁) ではなくミリ秒 (13桁) であること"
    assert h["sign"] and h["nonce"] and h["Authorization"]


def test_reads_meter_pro_fields(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(switchbot.httpx, "Client", _fake_client(
        {"statusCode": 100, "body": {"temperature": 26.1, "humidity": 61,
                                     "CO2": 644, "battery": 100}}))
    r = switchbot.read_bedroom()
    assert (r.temp_c, r.humidity_pct, r.co2_ppm, r.battery_pct) == (26.1, 61.0, 644.0, 100.0)


def test_api_error_returns_none_not_zeros(monkeypatch):
    """失敗時は None。⚠️ 0 で埋めると「極寒の夜」「換気完璧の夜」という嘘になる。"""
    _configure(monkeypatch)
    monkeypatch.setattr(switchbot.httpx, "Client", _fake_client(
        {"statusCode": 401, "message": "Unauthorized"}))
    assert switchbot.read_bedroom() is None


def test_disabled_when_unconfigured(monkeypatch):
    from app.config import Settings

    monkeypatch.setattr(switchbot, "get_settings", lambda: Settings())
    assert switchbot.is_configured() is False
    assert switchbot.read_bedroom() is None


def test_job_skips_missing_fields_instead_of_writing_zero(db_engine, monkeypatch):
    """CO2 非搭載機などで欠ける項目は**書かない** (0 を入れない)。"""
    from sqlalchemy import select

    from app.db import session_scope
    from app.ingest import bedroom_env
    from app.models import MetricSample

    monkeypatch.setattr(
        bedroom_env, "read_bedroom",
        lambda: switchbot.BedroomReading(temp_c=25.0, humidity_pct=55.0,
                                         co2_ppm=None, battery_pct=90.0),
    )
    out = bedroom_env.bedroom_env_job.__wrapped__()
    assert out["written"] == 2

    with session_scope() as ses:
        keys = set(ses.execute(select(MetricSample.metric_key)).scalars())
    assert bedroom_env.CO2_KEY not in keys
    assert bedroom_env.TEMP_KEY in keys
