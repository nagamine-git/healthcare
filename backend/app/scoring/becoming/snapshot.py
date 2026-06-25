"""三層スナップショットの取得・バックフィル(DB)。"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.health import BecomingSnapshot, DailyScore, GardenDaily
from app.scoring.becoming.metrics import loop_week
from app.scoring.becoming.trajectory import project
from app.scoring.garden.compute import cell_focus
from app.scoring.identity.store import build_gap_report
from app.scoring.timewindow import app_today


def capture_snapshot(session: Session, target: date, *, include_identity: bool = True) -> BecomingSnapshot:
    """target 日の三層 snapshot を upsert。

    include_identity=False(過去日のバックフィル)では dim_estimates/overall を埋めない
    (アイデンティティの履歴は存在しないため、現在地を過去日に書くと嘘になる)。
    """
    settings = get_settings()
    score = session.get(DailyScore, target)
    condition = score.total if score else None

    gd = session.get(GardenDaily, target)
    garden_intensity = gd.intensity if gd else None
    garden_focus = (
        cell_focus(gd.contributions or {}, settings.garden_catalog, settings.garden_gap_gamma)
        if gd
        else None
    )

    overall_proximity: float | None = None
    dim_estimates: dict | None = None
    if include_identity:
        report = build_gap_report(session)
        overall_proximity = report.get("overall")
        dim_estimates = {
            d["id"]: d["current"]
            for d in report.get("dimensions", [])
            if d.get("current") is not None
        }

    row = session.get(BecomingSnapshot, target)
    if row is None:
        row = BecomingSnapshot(date=target)
        session.add(row)
    row.condition = condition
    row.garden_intensity = garden_intensity
    row.garden_focus = garden_focus
    if include_identity:
        row.overall_proximity = overall_proximity
        row.dim_estimates = dim_estimates
    row.captured_at = datetime.utcnow()
    session.flush()
    return row


def backfill_snapshots(session: Session, days: int = 120) -> int:
    """過去 days 日の condition・garden を埋める(identity は当日のみ実測)。"""
    today = app_today()
    count = 0
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        capture_snapshot(session, d, include_identity=(d == today))
        count += 1
    return count


def _snap_dict(row: BecomingSnapshot) -> dict:
    return {
        "date": row.date,
        "condition": row.condition,
        "garden_intensity": row.garden_intensity,
        "garden_focus": row.garden_focus,
        "overall_proximity": row.overall_proximity,
        "dim_estimates": row.dim_estimates or {},
    }


def build_becoming_report(session: Session) -> dict:
    """フライホイール + 到達予測 + 履歴をまとめて返す(API 用)。"""
    settings = get_settings()
    today = app_today()
    window_start = today - timedelta(days=settings.becoming_trajectory_window_days)
    rows = (
        session.query(BecomingSnapshot)
        .filter(BecomingSnapshot.date >= window_start)
        .order_by(BecomingSnapshot.date)
        .all()
    )
    snaps = [_snap_dict(r) for r in rows]

    week_start = today - timedelta(days=6)
    week = [s for s in snaps if s["date"] >= week_start]
    loop = loop_week(week, settings.becoming_good_condition_threshold)

    from app.scoring.identity.store import get_archetype

    _name, targets, weights = get_archetype(session)
    trajectory = project(
        snaps, targets, weights,
        settings.becoming_trajectory_window_days, settings.becoming_min_snapshots_for_eta,
    )

    history = [
        {"date": s["date"].isoformat(), "condition": s["condition"],
         "garden_focus": s["garden_focus"], "garden_intensity": s["garden_intensity"],
         "overall_proximity": s["overall_proximity"]}
        for s in snaps
    ]
    return {
        "date": today.isoformat(),
        "loop_week": loop,
        "trajectory": trajectory,
        "history": history,
    }
