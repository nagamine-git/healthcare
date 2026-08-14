"""SwitchBot API から寝室の環境 (温度・湿度・CO2) を取る。

# なぜ要るか
睡眠の質は室温に強く左右されるが、これまで室温は測れず**外気温を代理**にしていた
(``sleep_drivers`` の ``temp_night``)。寝室に MeterPro(CO2) があるので、代理をやめて
実測に置き換えられる。加えて **CO2** が取れるのが大きい: 寝室の CO2 上昇 (換気不足) は
睡眠の質と翌日の認知機能を落とすことが報告されており、既存のどの指標でも捕まえられて
いなかった。

# 認証
SwitchBot API v1.1 は HMAC-SHA256 署名。⚠️ ``t`` は**ミリ秒**エポック
(秒で送ると 401 になる)。署名対象は ``token + t + nonce`` の連結。

# 設定
env: ``SWITCHBOT_TOKEN`` / ``SWITCHBOT_SECRET`` / ``SWITCHBOT_BEDROOM_DEVICE_ID``
未設定なら全ての取得関数が None を返す (機能ごと無効化。他を巻き込まない)。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)

_BASE = "https://api.switch-bot.com/v1.1"
_TIMEOUT_S = 8.0


@dataclass(frozen=True)
class BedroomReading:
    """寝室の1時点の環境値。取れなかった項目は None。"""

    temp_c: float | None
    humidity_pct: float | None
    co2_ppm: float | None
    battery_pct: float | None


def _headers(token: str, secret: str) -> dict[str, str]:
    t = str(int(time.time() * 1000))  # ⚠️ ミリ秒。秒だと 401
    nonce = uuid.uuid4().hex
    mac = hmac.new(
        secret.encode("utf-8"), f"{token}{t}{nonce}".encode(), digestmod=hashlib.sha256
    )
    return {
        "Authorization": token,
        "sign": base64.b64encode(mac.digest()).decode("utf-8"),
        "nonce": nonce,
        "t": t,
        "Content-Type": "application/json; charset=utf8",
    }


def _as_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def is_configured() -> bool:
    s = get_settings()
    return bool(s.switchbot_token and s.switchbot_secret and s.switchbot_bedroom_device_id)


def read_bedroom() -> BedroomReading | None:
    """寝室メーターの現在値。未設定・失敗時は None (呼び出し側は記録をスキップ)。

    ⚠️ 失敗を 0 や既定値で埋めない。室温 0℃ や CO2 0ppm が分析に混ざると
    「その夜だけ極端に寒かった/換気が完璧だった」という嘘のデータになる。
    """
    s = get_settings()
    if not is_configured():
        return None
    url = f"{_BASE}/devices/{s.switchbot_bedroom_device_id}/status"
    try:
        with httpx.Client(timeout=_TIMEOUT_S) as client:
            r = client.get(url, headers=_headers(s.switchbot_token, s.switchbot_secret))
            r.raise_for_status()
            payload = r.json()
    except Exception as exc:
        logger.warning("switchbot_fetch_failed", error=str(exc))
        return None

    if payload.get("statusCode") != 100:
        logger.warning(
            "switchbot_api_error",
            status_code=payload.get("statusCode"), message=payload.get("message", ""),
        )
        return None

    body = payload.get("body") or {}
    return BedroomReading(
        temp_c=_as_float(body.get("temperature")),
        humidity_pct=_as_float(body.get("humidity")),
        # MeterPro(CO2) は "CO2"。CO2 非搭載の機種では欠ける
        co2_ppm=_as_float(body.get("CO2")),
        battery_pct=_as_float(body.get("battery")),
    )
