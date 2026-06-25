"""GitHub のコミット履歴(contribution calendar)を日次で取り込む。"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import session_scope
from app.logging import get_logger
from app.models.health import GardenConfig, GithubContributionDaily

logger = get_logger(__name__)

_GRAPHQL_URL = "https://api.github.com/graphql"
_QUERY = """
query($from: DateTime!, $to: DateTime!) {
  viewer {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""


def resolve_github_credentials(session: Session) -> tuple[str | None, str | None]:
    """GitHub 認証情報を解決(DB GardenConfig 優先、無ければ settings フォールバック)。"""
    cfg = session.get(GardenConfig, 1)
    if cfg is not None and cfg.github_token:
        return cfg.github_username, cfg.github_token
    s = get_settings()
    return s.github_username, s.github_token


def parse_contribution_calendar(payload: dict) -> dict[date, int]:
    weeks = (
        payload.get("data", {})
        .get("viewer", {})
        .get("contributionsCollection", {})
        .get("contributionCalendar", {})
        .get("weeks", [])
    )
    out: dict[date, int] = {}
    for w in weeks:
        for d in w.get("contributionDays", []):
            out[date.fromisoformat(d["date"])] = int(d.get("contributionCount", 0))
    return out


def _fetch_calendar(username: str | None, token: str, days: int) -> dict | None:
    to = datetime.now(UTC)
    frm = to - timedelta(days=days)
    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.post(
                _GRAPHQL_URL,
                headers={"Authorization": f"bearer {token}"},
                json={
                    "query": _QUERY,
                    "variables": {"from": frm.isoformat(), "to": to.isoformat()},
                },
            )
            r.raise_for_status()
            return r.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("github_fetch_failed", error=str(exc))
        return None


def sync_github(session: Session, *, days: int = 60) -> dict:
    username, token = resolve_github_credentials(session)
    if not token:
        return {"status": "skipped", "reason": "no_credentials"}
    payload = _fetch_calendar(username, token, days)
    if payload is None:
        return {"status": "error"}
    calendar = parse_contribution_calendar(payload)
    upserted = 0
    for d, count in calendar.items():
        row = session.get(GithubContributionDaily, d)
        if row is None:
            row = GithubContributionDaily(date=d)
            session.add(row)
        row.commit_count = count
        row.updated_at = datetime.utcnow()
        upserted += 1
    session.flush()
    logger.info("github_sync_done", days=days, upserted=upserted)
    return {"status": "ok", "upserted": upserted}


async def github_sync_job() -> dict:
    with session_scope() as session:
        return sync_github(session)
