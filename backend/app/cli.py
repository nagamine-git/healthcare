"""Small CLI for one-off operations (initial Garmin login, manual recompute, etc.).

Usage:
    python -m app.cli garmin-login
    python -m app.cli recompute [YYYY-MM-DD]
    python -m app.cli regenerate-advice [YYYY-MM-DD]
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date as date_type
from datetime import datetime


def _setup() -> None:
    from app.config import get_settings
    from app.db import create_all, init_engine
    from app.logging import configure_logging

    settings = get_settings()
    configure_logging(settings.app_log_level)
    init_engine(settings.resolved_db_path())
    create_all()


def cmd_garmin_login() -> int:
    _setup()
    from app.config import get_settings
    from app.ingest.garmin_client import GarminClient

    settings = get_settings()
    if not (settings.garmin_email and settings.garmin_password):
        print("GARMIN_EMAIL / GARMIN_PASSWORD が未設定です。")
        return 2

    client = GarminClient.from_settings(settings)
    client.login()
    print("Garmin login successful. Token cached at:", settings.resolved_garmin_token_dir())
    return 0


def cmd_recompute(args: list[str]) -> int:
    _setup()
    from app.scoring.recompute import recompute_for_date

    target = _parse_date(args[0]) if args else date_type.today()
    result = recompute_for_date(target)
    print(target.isoformat(), result)
    return 0


def cmd_regenerate_advice(args: list[str]) -> int:
    _setup()
    from app.llm.client import generate_advice_for_date

    target = _parse_date(args[0]) if args else date_type.today()
    result = asyncio.run(generate_advice_for_date(target, force=True))
    print(target.isoformat(), result)
    return 0


def cmd_sync_garmin() -> int:
    _setup()
    from app.ingest.garmin_sync import sync_garmin_job

    result = asyncio.run(sync_garmin_job())
    print(result)
    return 0


def cmd_gcal_login() -> int:
    _setup()
    from app.integrations.gcal import run_installed_app_flow

    path = run_installed_app_flow()
    print(f"Google Calendar 認可成功。token を保存: {path}")
    return 0


def cmd_gcal_schedule(args: list[str]) -> int:
    _setup()
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from sqlalchemy import select

    from app.db import session_scope
    from app.integrations.gcal import schedule_actions_from_comment
    from app.models import LlmComment

    target = _parse_date(args[0]) if args else date_type.today()
    with session_scope() as session:
        latest = session.execute(
            select(LlmComment)
            .where(LlmComment.date == target)
            .order_by(LlmComment.generated_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        comment_text = latest.comment if latest else None

    if not comment_text:
        print(f"{target}: アドバイスがまだ生成されていません。先に regenerate-advice を実行")
        return 1

    now_jst = datetime.now(ZoneInfo("Asia/Tokyo"))
    created = schedule_actions_from_comment(comment_text, target_date=now_jst)
    print(f"作成イベント数: {len(created)}")
    for ev in created:
        print(f"  {ev['start']} {ev['summary']}  → {ev.get('htmlLink')}")
    return 0


def _parse_date(value: str) -> date_type:
    return datetime.strptime(value, "%Y-%m-%d").date()


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    cmd, *rest = argv
    if cmd == "garmin-login":
        return cmd_garmin_login()
    if cmd == "sync-garmin":
        return cmd_sync_garmin()
    if cmd == "recompute":
        return cmd_recompute(rest)
    if cmd == "regenerate-advice":
        return cmd_regenerate_advice(rest)
    if cmd == "gcal-login":
        return cmd_gcal_login()
    if cmd == "gcal-schedule":
        return cmd_gcal_schedule(rest)
    print(f"Unknown command: {cmd}")
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
