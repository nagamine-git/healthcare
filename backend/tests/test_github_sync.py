from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ingest.github_sync import (
    parse_contribution_calendar,
    resolve_github_credentials,
    sync_and_backfill,
    sync_github,
)
from app.models.health import Base, GardenConfig, GardenDaily, GithubContributionDaily


@pytest.fixture
def mem_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


SAMPLE = {
    "data": {"viewer": {"contributionsCollection": {"contributionCalendar": {"weeks": [
        {"contributionDays": [
            {"date": "2026-06-24", "contributionCount": 0},
            {"date": "2026-06-25", "contributionCount": 5},
        ]},
    ]}}}}
}


def test_parse_contribution_calendar():
    assert parse_contribution_calendar(SAMPLE) == {date(2026, 6, 24): 0, date(2026, 6, 25): 5}


def test_resolve_credentials_prefers_db(mem_session):
    mem_session.add(GardenConfig(id=1, github_username="dbuser", github_token="dbtok"))
    mem_session.flush()
    assert resolve_github_credentials(mem_session) == ("dbuser", "dbtok")


def test_resolve_credentials_none_when_unset(mem_session):
    assert resolve_github_credentials(mem_session) == (None, None)


def test_sync_github_noop_without_credentials(mem_session):
    assert sync_github(mem_session)["status"] == "skipped"


def test_sync_github_upserts(mem_session, monkeypatch):
    mem_session.add(GardenConfig(id=1, github_username="octocat", github_token="tok"))
    mem_session.flush()
    import app.ingest.github_sync as gs

    monkeypatch.setattr(gs, "_fetch_calendar", lambda user, token, days: SAMPLE)
    out = sync_github(mem_session, days=30)
    assert out["status"] == "ok"
    assert mem_session.get(GithubContributionDaily, date(2026, 6, 25)).commit_count == 5
    sync_github(mem_session, days=30)
    assert mem_session.query(GithubContributionDaily).filter_by(date=date(2026, 6, 25)).count() == 1


def test_sync_and_backfill_creates_garden_rows(mem_session, monkeypatch):
    mem_session.add(GardenConfig(id=1, github_username="octocat", github_token="tok"))
    mem_session.flush()
    import app.ingest.github_sync as gs

    monkeypatch.setattr(gs, "_fetch_calendar", lambda user, token, days: SAMPLE)
    monkeypatch.setattr(gs, "app_today", lambda: date(2026, 6, 25))
    out = sync_and_backfill(mem_session, days=2)
    assert out["status"] == "ok"
    # 6/25 はコミット5 → 草あり
    assert mem_session.get(GardenDaily, date(2026, 6, 25)).intensity > 0


def test_sync_and_backfill_skips_without_credentials(mem_session, monkeypatch):
    monkeypatch.setattr(__import__("app.ingest.github_sync", fromlist=["app_today"]),
                        "app_today", lambda: date(2026, 6, 25))
    out = sync_and_backfill(mem_session, days=2)
    assert out["status"] == "skipped"
