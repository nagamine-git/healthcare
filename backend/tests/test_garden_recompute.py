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
    recompute_garden_range,
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
        {"kind": "aerobic", "source": "garmin_aerobic", "dimensions": [], "base": 1.5, "evidence": ""},
        {"kind": "meditation", "source": "manual", "dimensions": [], "base": 1.2, "evidence": ""},
    ]
    assert active_kinds_for_date(mem_session, d, catalog) == {"coding", "aerobic", "meditation"}


def test_active_kinds_detects_strength_sleep_steps(mem_session):
    from app.models.health import DailySummary, SleepSession

    d = date(2026, 6, 25)
    mem_session.add(Workout(id="s1", source="garmin", start=datetime(2026, 6, 25, 8, 0),
                            type="strength_training"))
    mem_session.add(SleepSession(date=d, source="garmin", total_min=460))
    mem_session.add(DailySummary(date=d, steps=9000))
    mem_session.flush()
    catalog = [
        {"kind": "strength", "source": "garmin_strength", "dimensions": [], "base": 1.5, "evidence": ""},
        {"kind": "sleep", "source": "sleep", "dimensions": [], "base": 1.3, "evidence": ""},
        {"kind": "steps", "source": "steps", "dimensions": [], "base": 1.0, "evidence": ""},
        {"kind": "aerobic", "source": "garmin_aerobic", "dimensions": [], "base": 1.5, "evidence": ""},
    ]
    # 筋トレのみ(有酸素なし)+ 十分な睡眠 + 歩数達成
    assert active_kinds_for_date(mem_session, d, catalog) == {"strength", "sleep", "steps"}


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


def test_recompute_range_backfills_history_and_streak(mem_session, monkeypatch):
    import app.scoring.garden.recompute as rc

    monkeypatch.setattr(rc, "build_gap_report", lambda s: {"dimensions": []})
    monkeypatch.setattr(rc, "get_settings", lambda: _FakeSettings())

    # 6/23・6/24 に GitHub コミット、6/25 は無し
    mem_session.add(GithubContributionDaily(date=date(2026, 6, 23), commit_count=2))
    mem_session.add(GithubContributionDaily(date=date(2026, 6, 24), commit_count=1))
    mem_session.flush()

    n = recompute_garden_range(mem_session, date(2026, 6, 23), date(2026, 6, 25))
    assert n == 3
    r23 = mem_session.get(GardenDaily, date(2026, 6, 23))
    r24 = mem_session.get(GardenDaily, date(2026, 6, 24))
    r25 = mem_session.get(GardenDaily, date(2026, 6, 25))
    assert r23.intensity > 0 and r23.streak_len == 1
    assert r24.intensity > 0 and r24.streak_len == 2  # 連続2日
    assert r25.intensity == 0 and r25.streak_len == 0  # 活動なしで途切れる


def test_recompute_for_date_accepts_precomputed_gaps(mem_session, monkeypatch):
    import app.scoring.garden.recompute as rc

    # build_gap_report が呼ばれたら失敗させ、gaps を渡せばスキップされることを確認
    def _boom(_s):
        raise AssertionError("build_gap_report should not be called when gaps is given")

    monkeypatch.setattr(rc, "build_gap_report", _boom)
    monkeypatch.setattr(rc, "get_settings", lambda: _FakeSettings())
    mem_session.add(GoodActionLog(ts=datetime(2026, 6, 25, 1, 0), kind="meditation", source="manual"))
    mem_session.flush()
    row = recompute_garden_for_date(mem_session, date(2026, 6, 25), gaps={})
    assert row.intensity > 0


class _FakeSettings:
    garden_catalog: ClassVar[list[dict]] = [
        {"kind": "meditation", "source": "manual", "dimensions": ["internal_locus"],
         "base": 1.2, "evidence": ""},
        {"kind": "coding", "source": "github", "dimensions": ["ownership"],
         "base": 2.0, "evidence": ""},
    ]
    garden_gap_gamma = 1.0
    garden_level_thresholds: ClassVar[list[float]] = [0.0, 1.0, 2.5, 4.5]
    garden_good_sleep_min = 420
    garden_steps_goal = 8000
