"""Google Calendar 連携。

OAuth 2.0 (installed app) フローでユーザーから認可を 1 回だけ取得し、
refresh token を ``/data/google_tokens/token.json`` に永続化する。
以降はバックエンドが refresh token から access token を取り直してカレンダーに
イベントを書き込む。

Client secret は同じ ``/data/google_tokens/client_secret.json`` に置く。
1Password から取り出すスクリプトは ``bin/gcal-login.sh`` 参照。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from app.logging import get_logger

logger = get_logger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

CLIENT_SECRET_FILENAME = "client_secret.json"
TOKEN_FILENAME = "token.json"


def _token_dir(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    p = settings.app_data_dir / "google_tokens"
    p.mkdir(parents=True, exist_ok=True)
    return p


def client_secret_path(settings: Settings | None = None) -> Path:
    return _token_dir(settings) / CLIENT_SECRET_FILENAME


def token_path(settings: Settings | None = None) -> Path:
    return _token_dir(settings) / TOKEN_FILENAME


def has_token() -> bool:
    return token_path().exists()


def load_credentials():
    """有効な Credentials を返す。token が無い・refresh 失敗時は None。"""
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    path = token_path()
    if not path.exists():
        return None
    creds = Credentials.from_authorized_user_file(str(path), SCOPES)
    if creds.valid:
        return creds
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError as exc:
            logger.warning("gcal_refresh_failed", error=str(exc))
            return None
        # 更新された access_token を含めて再保存
        path.write_text(creds.to_json())
        return creds
    return None


def run_installed_app_flow(*, open_browser: bool | None = None, port: int = 0) -> str:
    """対話 OAuth フロー (端末ブラウザで認可) → token.json を保存。

    CLI 実行を想定。デフォルトでは GUI のあるホストで動かす想定で、
    ブラウザを自動起動する。``HEADLESS=1`` か ``open_browser=False`` で抑制。
    """
    import os

    from google_auth_oauthlib.flow import InstalledAppFlow

    cs = client_secret_path()
    if not cs.exists():
        raise FileNotFoundError(
            f"client secret が無い: {cs}. 'op document get gog-efg > {cs}' などで配置してください"
        )

    if open_browser is None:
        open_browser = os.environ.get("HEADLESS", "0") not in ("1", "true", "True")

    flow = InstalledAppFlow.from_client_secrets_file(str(cs), SCOPES)
    creds = flow.run_local_server(
        port=port,
        open_browser=open_browser,
        bind_addr="127.0.0.1",
        prompt="consent",
        access_type="offline",
    )
    out = token_path()
    out.write_text(creds.to_json())
    out.chmod(0o600)
    return str(out)


# ---- Calendar API helpers ------------------------------------------------


def _calendar_service():
    from googleapiclient.discovery import build

    creds = load_credentials()
    if creds is None:
        raise RuntimeError(
            "Google Calendar の認証情報が無いか期限切れです。"
            "'docker compose exec backend python -m app.cli gcal-login' を再実行してください。"
        )
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


_ADJUSTABLE_MARKER = "[hc-adjustable]"


def list_events_for_date(
    target_date,
    *,
    calendar_id: str = "primary",
    timezone: str = "Asia/Tokyo",
) -> list[dict[str, Any]]:
    """指定日 (JST) の予定一覧を返す。終日予定は除外。

    各イベントに次のフラグを付与:
    - ``is_hc_managed``: Healthcare が作った (extendedProperties.private.hc_managed=1)
    - ``is_adjustable``: 上記 or description に ``[hc-adjustable]`` を含む

    認証情報が無い場合は空リストを返す。
    """
    creds = load_credentials()
    if creds is None:
        return []
    try:
        from zoneinfo import ZoneInfo

        from googleapiclient.discovery import build

        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        tz = ZoneInfo(timezone)
        start_dt = datetime.combine(target_date, datetime.min.time(), tz)
        end_dt = start_dt + timedelta(days=1)
        result = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=start_dt.isoformat(),
                timeMax=end_dt.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                maxResults=50,
            )
            .execute()
        )
        events = []
        for ev in result.get("items", []):
            start = ev.get("start", {}).get("dateTime")
            end = ev.get("end", {}).get("dateTime")
            if not start or not end:
                continue
            summary = ev.get("summary", "") or "(no title)"
            description = ev.get("description", "") or ""
            ext = (ev.get("extendedProperties") or {}).get("private") or {}
            is_managed = ext.get("hc_managed") == "1"
            is_adjustable = is_managed or (_ADJUSTABLE_MARKER in description)
            transparency = ev.get("transparency", "opaque")
            events.append(
                {
                    "id": ev.get("id"),
                    "summary": summary,
                    "start": start,
                    "end": end,
                    "is_busy": transparency == "opaque",
                    "is_hc_managed": is_managed,
                    "is_adjustable": is_adjustable,
                }
            )
        return events
    except Exception as exc:
        logger.warning("gcal_list_events_failed", error=str(exc))
        return []


def delete_managed_events_for_date(
    target_date, *, calendar_id: str = "primary"
) -> int:
    """指定日の Healthcare 管理イベントを全て削除する。返り値は削除件数。"""
    creds = load_credentials()
    if creds is None:
        return 0
    deleted = 0
    try:
        from googleapiclient.discovery import build

        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        for ev in list_events_for_date(target_date, calendar_id=calendar_id):
            if not ev.get("is_hc_managed"):
                continue
            ev_id = ev.get("id")
            if not ev_id:
                continue
            try:
                service.events().delete(calendarId=calendar_id, eventId=ev_id).execute()
                deleted += 1
            except Exception as exc:
                logger.warning("gcal_delete_failed", id=ev_id, error=str(exc))
    except Exception as exc:
        logger.warning("gcal_delete_managed_failed", error=str(exc))
    return deleted


def create_event(
    *,
    summary: str,
    start: datetime,
    end: datetime,
    description: str | None = None,
    calendar_id: str = "primary",
    color_id: str | None = None,
    hc_action_id: str | None = None,
) -> dict[str, Any]:
    """Healthcare 管理イベントとして作成する (extendedProperties.private.hc_managed=1)。"""
    import uuid as _uuid

    service = _calendar_service()
    body: dict[str, Any] = {
        "summary": summary,
        "start": {"dateTime": start.isoformat(), "timeZone": "Asia/Tokyo"},
        "end": {"dateTime": end.isoformat(), "timeZone": "Asia/Tokyo"},
        "extendedProperties": {
            "private": {
                "hc_managed": "1",
                "hc_action_id": hc_action_id or str(_uuid.uuid4()),
            }
        },
    }
    if description:
        body["description"] = description
    if color_id:
        body["colorId"] = color_id
    return service.events().insert(calendarId=calendar_id, body=body).execute()


# ---- LLM advice → schedulable actions ------------------------------------


_ACTION_LINE = re.compile(
    r"^[-・•]\s*\[?(?P<time>\d{1,2}[::]\d{2})\]?\s*(?P<rest>.+)$"
)
_DURATION_PAT = re.compile(r"(?P<num>\d{1,3})\s*分")


def schedule_actions_from_comment(
    comment: str,
    *,
    target_date: datetime,
    calendar_id: str = "primary",
    color_id: str | None = "9",
) -> list[dict[str, Any]]:
    """テキストパース版 (フォールバック)。新しい構造化版がある場合はそちらを優先。"""
    actions = parse_advice_actions(comment, target_date)
    return _create_calendar_events(actions, target_date, calendar_id, color_id)


def parse_advice_actions(comment: str, today: datetime) -> list[dict[str, Any]]:
    """LLM のアドバイスから「[HH:MM] 行動 (所要 N 分, …)」を抜き出す。

    ``today`` は JST aware datetime を渡す前提。所要時間が見つからない行は 30 分とする。
    """
    actions: list[dict[str, Any]] = []
    in_actions_block = False
    for raw_line in comment.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "推奨アクション" in line:
            in_actions_block = True
            continue
        if line.startswith("【") and "推奨アクション" not in line:
            in_actions_block = False
            continue
        if not in_actions_block:
            continue
        m = _ACTION_LINE.match(line)
        if not m:
            continue
        h, _, mn = m.group("time").partition(":")
        try:
            start = today.replace(hour=int(h), minute=int(mn), second=0, microsecond=0)
        except ValueError:
            continue
        rest = m.group("rest").strip()
        d_match = _DURATION_PAT.search(rest)
        duration_min = int(d_match.group("num")) if d_match else 30
        # rest の先頭部分 (括弧前) をタイトル候補に
        if "(" in rest:
            title = rest.split("(", 1)[0].strip(" 　")
        elif "（" in rest:
            title = rest.split("（", 1)[0].strip(" 　")
        else:
            title = rest
        actions.append(
            {
                "title": title or rest,
                "start": start,
                "end": start + timedelta(minutes=duration_min),
                "duration_min": duration_min,
                "description": rest,
            }
        )
    return actions


def schedule_actions_from_payload(
    payload: dict[str, Any],
    *,
    target_date: datetime,
    calendar_id: str = "primary",
    color_id: str | None = "9",  # Blueberry
) -> list[dict[str, Any]]:
    """構造化 advice payload (tool_use input) から Calendar イベントを作る。

    parse_advice_actions のテキスト解析を経由しないので、絵文字や見出しの
    変動に左右されない。``actions[]`` の各要素が時刻・所要時間を持つ前提。
    """
    actions_raw = payload.get("actions") or []
    actions: list[dict[str, Any]] = []
    for a in actions_raw:
        time_jst = a.get("time_jst") or ""
        try:
            h, _, mn = time_jst.partition(":")
            start = target_date.replace(
                hour=int(h), minute=int(mn), second=0, microsecond=0
            )
        except (ValueError, TypeError):
            continue
        duration = int(a.get("duration_min") or 30)
        bits = [a.get("title", "")]
        if intensity := a.get("intensity"):
            bits.append(f"強度: {intensity}")
        if why := a.get("why"):
            bits.append(f"理由: {why}")
        actions.append(
            {
                "title": a.get("title", "(no title)"),
                "start": start,
                "end": start + timedelta(minutes=duration),
                "duration_min": duration,
                "description": " / ".join(b for b in bits if b),
            }
        )
    return _create_calendar_events(actions, target_date, calendar_id, color_id)


def _create_calendar_events(
    actions: list[dict[str, Any]],
    now: datetime,
    calendar_id: str,
    color_id: str | None,
) -> list[dict[str, Any]]:
    created: list[dict[str, Any]] = []
    for a in actions:
        if a["end"] < now:
            continue  # 過ぎた時刻は作らない
        try:
            ev = create_event(
                summary=f"[Healthcare] {a['title']}",
                start=a["start"],
                end=a["end"],
                description=a["description"],
                calendar_id=calendar_id,
                color_id=color_id,
            )
            created.append(
                {
                    "id": ev.get("id"),
                    "htmlLink": ev.get("htmlLink"),
                    "summary": ev.get("summary"),
                    "start": ev["start"]["dateTime"],
                    "end": ev["end"]["dateTime"],
                }
            )
        except Exception as exc:
            logger.warning("gcal_create_event_failed", title=a["title"], error=str(exc))
    return created
