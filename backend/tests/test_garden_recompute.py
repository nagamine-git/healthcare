from __future__ import annotations

from datetime import date, datetime
from typing import ClassVar

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.health import (
    Base,
    GardenDaily,
    GithubContributionDaily,
    GoodActionLog,
    Workout,
)
from app.scoring.garden.recompute import (
    active_kinds_for_date,
    gaps_from_report,
    recompute_garden_for_date,
)


@pytest.fixture
def mem_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_gaps_from_report():
    report = {"dimensions": [
        {"id": "ownership", "gap": 80.0},
        {"id": "internal_locus", "gap": None},
    ]}
    assert gaps_from_report(report) == {"ownership": 80.0, "internal_locus": None}


def test_active_kinds_collects_manual_workout_and_github(mem_session):
    d = date(2026, 6, 25)
    mem_session.add(GoodActionLog(ts=datetime(2026, 6, 25, 1, 0), kind="meditation", source="manual"))
    mem_session.add(Workout(id="w1", source="garmin", start=datetime(2026, 6, 25, 9, 0), type="running"))
    mem_session.add(GithubContributionDaily(date=d, commit_count=3))
    mem_session.flush()
    catalog = [
        {"kind": "coding", "source": "github", "dimensions": [], "base": 2.0, "evidence": ""},
        {"kind": "exercise", "source": "garmin", "dimensions": [], "base": 1.5, "evidence": ""},
        {"kind": "meditation", "source": "manual", "dimensions": [], "base": 1.2, "evidence": ""},
    ]
    assert active_kinds_for_date(mem_session, d, catalog) == {"coding", "exercise", "meditation"}


def test_active_kinds_github_zero_commits_not_active(mem_session):
    d = date(2026, 6, 25)
    mem_session.add(GithubContributionDaily(date=d, commit_count=0))
    mem_session.flush()
    catalog = [{"kind": "coding", "source": "github", "dimensions": [], "base": 2.0, "evidence": ""}]
    assert active_kinds_for_date(mem_session, d, catalog) == set()


def test_recompute_upserts_and_computes_streak(mem_session, monkeypatch):
    import app.scoring.garden.recompute as rc

    monkeypatch.setattr(rc, "build_gap_report", lambda s: {"dimensions": []})
    monkeypatch.setattr(rc, "get_settings", lambda: _FakeSettings())

    mem_session.add(GardenDaily(date=date(2026, 6, 24), intensity=1.2, level=1,
                                contributions={"meditation": 1.2}, streak_len=1))
    mem_session.add(GoodActionLog(ts=datetime(2026, 6, 25, 1, 0), kind="meditation", source="manual"))
    mem_session.flush()

    row = recompute_garden_for_date(mem_session, date(2026, 6, 25))
    assert row.date == date(2026, 6, 25)
    assert row.level >= 1
    assert row.streak_len == 2

    recompute_garden_for_date(mem_session, date(2026, 6, 25))
    count = mem_session.query(GardenDaily).filter(GardenDaily.date == date(2026, 6, 25)).count()
    assert count == 1


class _FakeSettings:
    garden_catalog: ClassVar[list[dict]] = [
        {"kind": "meditation", "source": "manual", "dimensions": ["internal_locus"],
         "base": 1.2, "evidence": ""},
    ]
    garden_gap_gamma = 1.0
    garden_level_thresholds: ClassVar[list[float]] = [0.0, 1.0, 2.5, 4.5]
