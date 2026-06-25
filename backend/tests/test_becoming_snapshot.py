from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.health import Base, BecomingSnapshot, DailyScore, GardenDaily
from app.scoring.becoming.snapshot import (
    backfill_snapshots,
    build_becoming_report,
    capture_snapshot,
)


@pytest.fixture
def mem_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_capture_snapshot_reads_condition_and_garden(mem_session):
    d = date(2026, 6, 25)
    mem_session.add(DailyScore(date=d, total=82.0, version="t", computed_at=datetime.utcnow()))
    mem_session.add(GardenDaily(date=d, intensity=3.6, level=3,
                                contributions={"coding": 3.6}, streak_len=1))
    mem_session.flush()
    row = capture_snapshot(mem_session, d)
    assert row.condition == 82.0
    assert row.garden_intensity == 3.6
    assert row.garden_focus is not None  # cell_focus が算出される


def test_backfill_past_days_have_no_identity(mem_session, monkeypatch):
    import app.scoring.becoming.snapshot as sn

    monkeypatch.setattr(sn, "app_today", lambda: date(2026, 6, 25))
    n = backfill_snapshots(mem_session, days=5)
    assert n == 5
    past = mem_session.get(BecomingSnapshot, date(2026, 6, 22))
    today = mem_session.get(BecomingSnapshot, date(2026, 6, 25))
    assert past.dim_estimates is None  # 過去日は identity を埋めない
    assert today.dim_estimates is not None  # 当日は実測(空 dict でも非 None)


def test_capture_is_idempotent(mem_session):
    d = date(2026, 6, 25)
    capture_snapshot(mem_session, d)
    capture_snapshot(mem_session, d)
    assert mem_session.query(BecomingSnapshot).filter_by(date=d).count() == 1


def test_build_report_shape(mem_session, monkeypatch):
    import app.scoring.becoming.snapshot as sn

    monkeypatch.setattr(sn, "app_today", lambda: date(2026, 6, 25))
    backfill_snapshots(mem_session, days=10)
    report = build_becoming_report(mem_session)
    assert {"date", "loop_week", "trajectory", "history"} <= set(report)
    assert {"capacity_utilization", "action_alignment", "identity_movement", "diagnosis"} <= set(
        report["loop_week"]
    )
    assert {"eta_days", "bottleneck_dimension", "confidence", "per_dimension"} <= set(
        report["trajectory"]
    )
