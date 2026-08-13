"""郵便番号 → 座標。天気・気圧の観測地点を自宅に合わせるために使う。

HeartRails Geo API (無料・APIキー不要・日本の郵便番号) を使う。
https://geoapi.heartrails.com/api/json?method=searchByPostal&postal=1000005

⚠️ 座標を設定しないと config の既定値 (東京駅) で天気を引くことになり、
**別の場所の気圧・気温で分析してしまう**。気圧は頭痛分析の要因に入っているので、
地点がずれると要因分析そのものが無意味になる。
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from app.logging import get_logger

logger = get_logger(__name__)

_URL = "https://geoapi.heartrails.com/api/json"
_POSTAL_RE = re.compile(r"^\d{7}$")


def normalise_postal(raw: str) -> str | None:
    """"100-0005" / "〒100-0005" / "1000005" → "1000005"。不正なら None。"""
    digits = re.sub(r"\D", "", raw or "")
    return digits if _POSTAL_RE.match(digits) else None


def lookup_postal(postal: str) -> dict[str, Any] | None:
    """郵便番号から緯度経度と地名を引く。引けなければ None (呼び出し側で既定へ)。"""
    code = normalise_postal(postal)
    if code is None:
        return None
    try:
        with httpx.Client(timeout=8.0) as client:
            r = client.get(_URL, params={"method": "searchByPostal", "postal": code})
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        logger.warning("geocode_postal_failed", postal=code, error=str(exc))
        return None

    locations = ((data or {}).get("response") or {}).get("location") or []
    if not locations:
        return None
    # 同一郵便番号に複数町丁が返ることがある。天気の格子は数 km なのでどれでも実質同じ。
    # 先頭を採り、地名は「都道府県 市区町村」までにする (町丁まで出すと表示が長い)。
    loc = locations[0]
    try:
        lat, lon = float(loc["y"]), float(loc["x"])
    except (KeyError, TypeError, ValueError):
        return None
    label = f"{loc.get('prefecture', '')}{loc.get('city', '')}".strip() or code
    return {"postal_code": code, "latitude": lat, "longitude": lon, "label": label}


def resolve_home_coords() -> tuple[float, float, str]:
    """天気・気圧を引く座標。プロフィールの自宅設定を優先し、無ければ config の既定。

    ⚠️ 既定は東京駅なので、自宅を設定していない人は別地点の天気で分析される。
    気圧は頭痛分析の要因なので、ここがずれると要因分析が無意味になる。
    読めなくても例外は投げない (天気が取れないだけで画面全体を壊さない)。
    """
    from app.config import get_settings

    s = get_settings()
    try:
        from sqlalchemy import select

        from app.db import session_scope
        from app.models import UserProfile

        with session_scope() as ses:
            row = ses.execute(
                select(UserProfile.home_latitude, UserProfile.home_longitude, UserProfile.home_label)
            ).first()
        if row and row[0] is not None and row[1] is not None:
            return float(row[0]), float(row[1]), (row[2] or s.weather_location_label)
    except Exception:
        pass
    return s.weather_latitude, s.weather_longitude, s.weather_location_label
