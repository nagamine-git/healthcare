"""天気/気圧キャッシュが GPS の揺れで外れないことの回帰テスト。

# なぜ (2026-08-03 の実障害)
キャッシュキーが小数4桁 (約11m) だったため、スマホから送られる GPS 座標が
数 m 揺れるだけで毎リクエストがキャッシュミスになり、`/api/today?lat=..&lon=..`
が実際に open-meteo を叩いて 0.1s → 2.9s になっていた。しかも `/api/today` は
Today 画面全体を止める gating リクエストなので、体感は「アプリが固まる」だった。
"""

from __future__ import annotations

from app.integrations.weather import _cache_key, _round_coords


def test_gps_jitter_hits_the_same_cache_key() -> None:
    """同じ場所での数十 m の揺れは同じキーに落ちる。"""
    base = _cache_key(35.6812, 139.7671)
    for dlat, dlon in [(0.0, 0.0), (0.00003, 0.00002), (0.0009, 0.0009), (-0.0008, 0.0007)]:
        assert _cache_key(35.6812 + dlat, 139.7671 + dlon) == base


def test_genuinely_different_places_differ() -> None:
    """km オーダーで離れていれば別のキーになる (丸めすぎていないこと)。"""
    assert _cache_key(35.6812, 139.7671) != _cache_key(35.70, 139.7671)
    assert _cache_key(35.6812, 139.7671) != _cache_key(35.6812, 139.79)


def test_fetch_uses_the_same_rounding_as_the_cache_key() -> None:
    """取得先とキャッシュキーの丸めが一致していること。

    ここがずれると「キーは当たるのに別地点のデータを返す」という最悪の形になる。
    """
    lat, lon = _round_coords(35.68127, 139.76713)
    assert _cache_key(35.68127, 139.76713) == _cache_key(lat, lon)
