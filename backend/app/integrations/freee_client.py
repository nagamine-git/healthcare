"""freee会計 API 連携 (法人の試算表を取得する)。

OAuth 2.0 (web app) フロー。ユーザーがブラウザで /admin/freee/oauth/start →
freee でログイン・許可 → /admin/freee/oauth/callback にリダイレクトされ、ここで
code を access/refresh token に交換して ``/data/freee_tokens/token.json`` に永続化する。
以降はバックエンドが refresh token から access token を取り直して試算表 API を呼ぶ。

個人の MoneyForward 連携 (スクショ OCR) と役割は同じだが、freee は正規の Web OAuth が
使えるので画面を経由せずリアルタイムに直接叩ける。
"""

from __future__ import annotations

import json
import secrets
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import Settings, get_settings
from app.logging import get_logger

logger = get_logger(__name__)

AUTHORIZE_URL = "https://accounts.secure.freee.co.jp/public_api/authorize"
TOKEN_URL = "https://accounts.secure.freee.co.jp/public_api/token"
API_BASE = "https://api.freee.co.jp"

TOKEN_FILENAME = "token.json"
STATE_FILENAME = "oauth_state.json"
STATE_TTL_SECONDS = 600  # 10分以内にコールバックが来なければ無効


def _token_dir(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    p = settings.app_data_dir / "freee_tokens"
    p.mkdir(parents=True, exist_ok=True)
    return p


def token_path(settings: Settings | None = None) -> Path:
    return _token_dir(settings) / TOKEN_FILENAME


def has_token() -> bool:
    return token_path().exists()


def redirect_uri(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    return f"{settings.freee_redirect_base}/admin/freee/oauth/callback"


def authorize_url(settings: Settings | None = None, *, state: str | None = None) -> str:
    settings = settings or get_settings()
    params = {
        "client_id": settings.freee_client_id,
        "redirect_uri": redirect_uri(settings),
        "response_type": "code",
        "prompt": "select_company",
    }
    if state:
        params["state"] = state
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def _state_path(settings: Settings | None = None) -> Path:
    return _token_dir(settings) / STATE_FILENAME


def generate_state(*, settings: Settings | None = None) -> str:
    """CSRF 対策の state を生成し検証用に一時保存する (single-use、STATE_TTL_SECONDS で失効)。"""
    state = secrets.token_urlsafe(32)
    p = _state_path(settings)
    p.write_text(json.dumps({"state": state, "created_at": time.time()}))
    p.chmod(0o600)
    return state


def verify_state(state: str, *, settings: Settings | None = None) -> bool:
    """コールバックの state を検証する。成功/失敗を問わず使い切り (再利用防止のため削除)。"""
    p = _state_path(settings)
    if not p.exists():
        return False
    try:
        data = json.loads(p.read_text())
    except (OSError, ValueError):
        return False
    finally:
        p.unlink(missing_ok=True)
    if time.time() - data.get("created_at", 0) > STATE_TTL_SECONDS:
        return False
    return secrets.compare_digest(data.get("state", ""), state)


def _save_tokens(data: dict[str, Any], *, settings: Settings | None = None) -> None:
    data = {**data, "obtained_at": time.time()}
    p = token_path(settings)
    p.write_text(json.dumps(data))
    p.chmod(0o600)


def _load_tokens() -> dict[str, Any] | None:
    p = token_path()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def exchange_code(code: str, *, settings: Settings | None = None) -> dict[str, Any]:
    """認可コード → access/refresh token に交換し、永続化して返す。"""
    settings = settings or get_settings()
    with httpx.Client(timeout=15.0) as client:
        r = client.post(TOKEN_URL, data={
            "grant_type": "authorization_code",
            "client_id": settings.freee_client_id,
            "client_secret": settings.freee_client_secret,
            "code": code,
            "redirect_uri": redirect_uri(settings),
        })
        r.raise_for_status()
        data = r.json()
    _save_tokens(data, settings=settings)
    return data


def _refresh(tokens: dict[str, Any], *, settings: Settings) -> dict[str, Any] | None:
    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.post(TOKEN_URL, data={
                "grant_type": "refresh_token",
                "client_id": settings.freee_client_id,
                "client_secret": settings.freee_client_secret,
                "refresh_token": tokens["refresh_token"],
            })
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        logger.warning("freee_token_refresh_failed", error=str(exc))
        return None
    _save_tokens(data, settings=settings)
    return data


def get_valid_access_token() -> str | None:
    """有効な access_token を返す。期限切れなら refresh。トークン無し/refresh失敗は None。"""
    settings = get_settings()
    tokens = _load_tokens()
    if tokens is None:
        return None
    # expires_in (秒) は obtained_at からの相対。60秒のマージンを持って早めに更新。
    expires_at = tokens.get("obtained_at", 0) + tokens.get("expires_in", 0) - 60
    if time.time() < expires_at:
        return tokens.get("access_token")
    refreshed = _refresh(tokens, settings=settings)
    return refreshed.get("access_token") if refreshed else None


def _api_get(path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    token = get_valid_access_token()
    if token is None:
        return None
    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.get(
                f"{API_BASE}{path}",
                headers={"Authorization": f"Bearer {token}"},
                params=params or {},
            )
            r.raise_for_status()
            return r.json()
    except Exception as exc:
        logger.warning("freee_api_get_failed", path=path, error=str(exc))
        return None


def get_company() -> dict[str, Any] | None:
    """連携先の事業所 (最初の1件。複数事業所は将来対応)。{id, name} を返す。"""
    data = _api_get("/api/1/companies")
    companies = (data or {}).get("companies") or []
    if not companies:
        return None
    c = companies[0]
    return {"id": c.get("id"), "name": c.get("display_name") or c.get("name")}


def fetch_trial_bs(company_id: int) -> dict[str, Any] | None:
    """試算表(貸借対照表)。総資産/負債/純資産/当期純損益を含む。"""
    data = _api_get("/api/1/reports/trial_bs", params={"company_id": company_id})
    return (data or {}).get("trial_bs")


def fetch_trial_pl(company_id: int) -> dict[str, Any] | None:
    """試算表(損益計算書)。売上/営業損益/費目別の内訳を含む。"""
    data = _api_get("/api/1/reports/trial_pl", params={"company_id": company_id})
    return (data or {}).get("trial_pl")


def fetch_walletables(company_id: int) -> list[dict[str, Any]]:
    """銀行口座/現金口座の一覧 (残高そのものは含まない。参照用)。"""
    data = _api_get("/api/1/walletables", params={"company_id": company_id})
    return (data or {}).get("walletables") or []
