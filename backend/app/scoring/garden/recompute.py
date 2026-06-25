"""DB から当日の行動を収集し GardenDaily を再計算・upsert する。"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.health import (
    GardenDaily,
    GithubContributionDaily,
    GoodActionLog,
    Workout,
)
from app.scoring.garden.compute import compute_garden_day
from app.scoring.identity.store import build_gap_report


def gaps_from_report(report: dict) -> dict[str, float | None]:
    """build_gap_report の出力を {dimension_id: gap} へ。"""
    return {d["id"]: d.get("gap") for d in report.get("dimensions", [])}


def _day_bounds(target: date) -> tuple[datetime, datetime]:
    """target 日の素朴な [start, end)。DB は UTC naive、既存の手動ログ系と同じ素朴さ。"""
    start = datetime(target.year, target.month, target.day)
    return start, start + timedelta(days=1)


def active_kinds_for_date(session: Session, target: date, catalog: list[dict]) -> set[str]:
    """その日に観測された行動種別の集合。"""
    sources = {c["kind"]: c["source"] for c in catalog}
    start, end = _day_bounds(target)
    active: set[str] = set()

    # 手動 / apple_health 由来の GoodActionLog
    log_kinds = session.execute(
        select(GoodActionLog.kind)
        .where(GoodActionLog.ts >= start, GoodActionLog.ts < end)
        .distinct()
    ).scalars().all()
    active.update(log_kinds)

    # GitHub: commit_count>0 → source==github の kind を active 化
    gh = session.get(GithubContributionDaily, target)
    if gh is not None and (gh.commit_count or 0) > 0:
        active.update(k for k, src in sources.items() if src == "github")

    # Garmin: その日に Workout があれば source==garmin の kind を active 化
    workout_exists = session.execute(
        select(func.count())
        .select_from(Workout)
        .where(Workout.start >= start, Workout.start < end)
    ).scalar_one()
    if workout_exists:
        active.update(k for k, src in sources.items() if src == "garmin")

    return {k for k in active if k in sources}


def _streak_len(session: Session, target: date, has_today: bool) -> int:
    if not has_today:
        return 0
    length = 1
    cursor = target - timedelta(days=1)
    while True:
        row = session.get(GardenDaily, cursor)
        if row is not None and row.intensity > 0:
            length += 1
            cursor -= timedelta(days=1)
        else:
            break
    return length


def recompute_garden_for_date(session: Session, target: date) -> GardenDaily:
    settings = get_settings()
    catalog = settings.garden_catalog
    gaps = gaps_from_report(build_gap_report(session))
    active = active_kinds_for_date(session, target, catalog)
    result = compute_garden_day(
        active, catalog, gaps,
        settings.garden_gap_gamma, settings.garden_level_thresholds,
    )

    row = session.get(GardenDaily, target)
    if row is None:
        row = GardenDaily(date=target)
        session.add(row)
    row.intensity = result["intensity"]
    row.level = result["level"]
    row.contributions = result["contributions"]
    row.updated_at = datetime.utcnow()
    row.streak_len = _streak_len(session, target, result["intensity"] > 0)
    session.flush()
    return row
