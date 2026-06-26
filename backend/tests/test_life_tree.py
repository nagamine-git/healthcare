from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.health import Base, GardenDaily, Goal
from app.scoring.life.tree import active_goal, aggregate_tree, freq_achievement


def test_aggregate_tree_life_score_and_breach():
    ach = {"body": 50.0, "mind": 80.0, "intellect": 60.0,
           "creation": 90.0, "relationships": 40.0, "economy": None}
    weights = {"creation": 3.0, "body": 1.0, "mind": 1.0, "intellect": 1.0,
               "relationships": 1.0, "economy": 1.0}
    floors = {"body": 55.0, "relationships": 40.0}
    out = aggregate_tree(ach, weights, floors)
    # economy は None → 除外。focus は最大重みの creation。
    assert out["focus_capital"] == "creation"
    # body=50<55 で breach、relationships=40 は >=40 で breach しない
    assert out["breaches"] == ["body"]
    # life_score = (50*1+80*1+60*1+90*3+40*1)/(1+1+1+3+1) = 500/7 ≈ 71.4
    assert out["life_score"] == 71.4
    assert len(out["capitals"]) == 6


@pytest.fixture
def mem_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_freq_achievement_counts_action_days(mem_session):
    t = date(2026, 6, 26)
    # 直近に瞑想が3日、目標7日 → 3/7*100 ≈ 42.9
    for d in (date(2026, 6, 24), date(2026, 6, 25), date(2026, 6, 26)):
        mem_session.add(GardenDaily(date=d, intensity=1.0, level=1,
                                    contributions={"meditation": 1.2}, streak_len=1))
    mem_session.add(GardenDaily(date=date(2026, 6, 23), intensity=2.0, level=2,
                                contributions={"coding": 2.0}, streak_len=1))  # 別kind
    mem_session.flush()
    a = freq_achievement(mem_session, ["meditation", "journaling"], t, window=14, target_days=7)
    assert a == round(3 / 7 * 100, 1)


def test_active_goal_seeds_default_when_none(mem_session):
    g = active_goal(mem_session)
    assert g["title"]
    assert "creation" in g["capital_weights"]
    # seed されて1件入る
    assert mem_session.query(Goal).count() == 1


def test_active_goal_returns_existing(mem_session):
    mem_session.add(Goal(title="自作目標", horizon="1年",
                         capital_weights={"creation": 2.0}, active=True))
    mem_session.flush()
    g = active_goal(mem_session)
    assert g["title"] == "自作目標"
