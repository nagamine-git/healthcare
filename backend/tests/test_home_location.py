"""自宅の位置 (天気・気圧の観測地点) の設定。"""

from __future__ import annotations

from app.integrations import geocode


def test_normalises_postal_input():
    for raw in ("1000005", "100-0005", "〒100-0005", " 100 0005 "):
        assert geocode.normalise_postal(raw) == "1000005"
    for bad in ("12345", "abcdefg", "", "10000056"):
        assert geocode.normalise_postal(bad) is None


def test_lookup_maps_postal_to_coords(monkeypatch):
    """外部 API のレスポンスから lat/lon と「都道府県+市区町村」を組む。"""
    class _R:
        def raise_for_status(self): pass
        def json(self):
            return {"response": {"location": [
                {"prefecture": "東京都", "city": "千代田区", "town": "丸の内",
                 "x": "139.763644", "y": "35.68002"},
            ]}}

    class _C:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, *a, **kw): return _R()

    monkeypatch.setattr(geocode.httpx, "Client", _C)
    got = geocode.lookup_postal("100-0005")
    assert got == {
        "postal_code": "1000005", "latitude": 35.68002,
        "longitude": 139.763644, "label": "東京都千代田区",
    }


def test_lookup_returns_none_when_unknown(monkeypatch):
    """引けなければ None。⚠️ ここで既定座標にフォールバックしない。

    「設定できた」と誤認させると、別地点の天気で分析し続けることになる。
    """
    class _R:
        def raise_for_status(self): pass
        def json(self): return {"response": {"location": None}}

    class _C:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, *a, **kw): return _R()

    monkeypatch.setattr(geocode.httpx, "Client", _C)
    assert geocode.lookup_postal("9999999") is None


def test_resolve_falls_back_to_config_without_profile(db_engine):
    from app.config import get_settings

    lat, lon, _ = geocode.resolve_home_coords()
    s = get_settings()
    assert (lat, lon) == (s.weather_latitude, s.weather_longitude)


def test_resolve_prefers_saved_home(db_engine, session):
    from app.models import UserProfile

    session.add(UserProfile(home_latitude=43.06, home_longitude=141.35, home_label="北海道札幌市"))
    session.commit()

    lat, lon, label = geocode.resolve_home_coords()
    assert (round(lat, 2), round(lon, 2)) == (43.06, 141.35)
    assert label == "北海道札幌市"
