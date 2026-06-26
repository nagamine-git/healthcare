"""DB から当日の行動を収集し GardenDaily を再計算・upsert する。"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.health import (
    DailySummary,
    GardenDaily,
    GithubContributionDaily,
    GoodActionLog,
    LearningSectionProgress,
    SleepSession,
    Workout,
)
from app.scoring.garden.compute import compute_garden_day
from app.scoring.identity.store import build_gap_report


def _is_strength(workout_type: str | None) -> bool:
    return bool(workout_type) and "strength" in workout_type.lower()


def gaps_from_report(report: dict) -> dict[str, float | None]:
    """build_gap_report の出力を {dimension_id: gap} へ。"""
    return {d["id"]: d.get("gap") for d in report.get("dimensions", [])}


def _day_bounds(target: date) -> tuple[datetime, datetime]:
    """target 日の素朴な [start, end)。DB は UTC naive、既存の手動ログ系と同じ素朴さ。"""
    start = datetime(target.year, target.month, target.day)
    return start, start + timedelta(days=1)


def active_kinds_for_date(session: Session, target: date, catalog: list[dict]) -> set[str]:
    """その日に観測された行動種別の集合。

    source 別に自動検出する。データ源の無い "manual" は GoodActionLog で拾う。
    """
    settings = get_settings()
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

    # --- 自動検出: 各 source が満たされたか ---
    gh = session.get(GithubContributionDaily, target)
    workout_types = session.execute(
        select(Workout.type).where(Workout.start >= start, Workout.start < end)
    ).scalars().all()
    sleep = session.get(SleepSession, target)
    summary = session.get(DailySummary, target)
    learned = session.execute(
        select(func.count())
        .select_from(LearningSectionProgress)
        .where(
            or_(
                LearningSectionProgress.read_at.between(start, end),
                LearningSectionProgress.rustlings_at.between(start, end),
                LearningSectionProgress.explained_at.between(start, end),
            )
        )
    ).scalar_one()

    detected = {
        "github": gh is not None and (gh.commit_count or 0) > 0,
        "garmin_aerobic": any(not _is_strength(t) for t in workout_types),
        "garmin_strength": any(_is_strength(t) for t in workout_types),
        "sleep": sleep is not None and (sleep.total_min or 0) >= settings.garden_good_sleep_min,
        "steps": summary is not None and (summary.steps or 0) >= settings.garden_steps_goal,
        "learning": learned > 0,
    }
    for kind, src in sources.items():
        if detected.get(src):
            active.add(kind)

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


def recompute_garden_for_date(
    session: Session, target: date, gaps: dict[str, float | None] | None = None
) -> GardenDaily:
    settings = get_settings()
    catalog = settings.garden_catalog
    if gaps is None:
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


def recompute_garden_range(session: Session, start: date, end: date) -> int:
    """[start, end] の全日を昇順で再計算(履歴バックフィル)。

    gaps は現在の Compass ギャップを 1 度だけ算出して全日に適用する
    (過去のギャップ snapshot は持たない=現在の盲点で重み付けする意図的な簡略化)。
    昇順に処理するので各日の streak は確定済みの前日行を正しく参照する。
    """
    gaps = gaps_from_report(build_gap_report(session))
    cur = start
    count = 0
    while cur <= end:
        recompute_garden_for_date(session, cur, gaps=gaps)
        cur += timedelta(days=1)
        count += 1
    return count
