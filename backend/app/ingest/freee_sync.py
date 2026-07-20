"""freee 試算表を取得し、CorporateFinanceSnapshot に日次で保存する。

外部取得 (freee API) → DB 書き込み、という役割は garmin_sync.py と同じ ingest 層。
診断ロジック (compute_corporate_finance) は scoring/corporate_finance.py に分離してある。
"""

from __future__ import annotations

from typing import Any

from app.db import session_scope
from app.integrations import freee_client
from app.logging import get_logger
from app.models.health import CorporateFinanceSnapshot
from app.scoring.corporate_finance import parse_trial_bs, parse_trial_pl
from app.scoring.timewindow import app_today

logger = get_logger(__name__)


def sync_corporate_finance() -> dict[str, Any]:
    """freee から試算表を取得し、今日のスナップショットを upsert する。"""
    if not freee_client.has_token():
        return {"status": "not_connected"}

    company = freee_client.get_company()
    if company is None or company.get("id") is None:
        return {"status": "error", "reason": "company not found"}

    trial_bs = freee_client.fetch_trial_bs(company["id"])
    if trial_bs is None:
        return {"status": "error", "reason": "trial_bs fetch failed"}

    parsed = parse_trial_bs(trial_bs)

    # 損益計算書は「どの費目が主因か」の内訳用 (ベストエフォート — 失敗しても
    # 貸借対照表ベースの同期自体は成立させる)。
    trial_pl = freee_client.fetch_trial_pl(company["id"])
    parsed_pl = parse_trial_pl(trial_pl) if trial_pl is not None else {}
    if trial_pl is None:
        logger.warning("freee_sync_trial_pl_fetch_failed")

    today = app_today()
    with session_scope() as session:
        row = session.get(CorporateFinanceSnapshot, today)
        if row is None:
            row = CorporateFinanceSnapshot(date=today)
            session.add(row)
        row.company_name = company.get("name")
        for k, v in {**parsed, **parsed_pl}.items():
            setattr(row, k, v)

    logger.info("freee_sync_ok", company=company.get("name"), date=today.isoformat())
    return {"status": "ok", "date": today.isoformat()}


async def freee_sync_job() -> None:
    """cron から呼ぶラッパー。未接続 (OAuth 未認可) なら静かに何もしない。"""
    result = sync_corporate_finance()
    if result["status"] == "error":
        logger.warning("freee_sync_job_failed", reason=result.get("reason"))
