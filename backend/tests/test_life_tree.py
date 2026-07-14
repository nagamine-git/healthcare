from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.health import Base, GardenDaily, Goal
from app.scoring.life.tree import (
    active_goal,
    aggregate_tree,
    flatten_atlas_scores,
    freq_achievement,
    leaf_achievement,
    recommend_allocation,
)


def test_recommend_allocation_prioritizes_breach_then_focus():
    caps = [
        {"key": "body", "label": "身体資本", "achievement": 30.0, "breach": True},
        {"key": "creation", "label": "創造・仕事", "achievement": 40.0, "breach": False},
        {"key": "mind", "label": "精神状態", "achievement": 90.0, "breach": False},
    ]
    weights = {"body": 1.0, "creation": 2.5, "mind": 1.0}
    out = recommend_allocation(caps, weights)
    # breach の body が最優先、次に 重み大×伸びしろの creation
    assert out[0]["capital"] == "body"
    assert out[1]["capital"] == "creation"
    assert "kinds" in out[0] and out[0]["kinds"]


def test_aggregate_tree_life_score_and_breach():
    caps = [
        {"key": "body", "label": "身体資本", "achievement": 50.0, "leaves": []},
        {"key": "mind", "label": "精神状態", "achievement": 80.0, "leaves": []},
        {"key": "intellect", "label": "知的資本", "achievement": 60.0, "leaves": []},
        {"key": "creation", "label": "創造・仕事", "achievement": 90.0, "leaves": []},
        {"key": "relationships", "label": "関係資本", "achievement": 40.0, "leaves": []},
        {"key": "economy", "label": "経済資本", "achievement": None, "leaves": []},
    ]
    weights = {"creation": 3.0, "body": 1.0, "mind": 1.0, "intellect": 1.0,
               "relationships": 1.0, "economy": 1.0}
    floors = {"body": 55.0, "relationships": 40.0}
    out = aggregate_tree(caps, weights, floors)
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


def test_freq_achievement_none_when_no_garden_logging(mem_session):
    # 庭ログが窓内に全く無い期間は「未計測」(None)。0=サボりと区別する。
    t = date(2026, 6, 26)
    a = freq_achievement(mem_session, ["reading"], t, window=14, target_days=7)
    assert a is None


def test_freq_achievement_zero_when_tracking_but_kind_absent(mem_session):
    # 庭ログはあるが当該 kind が無い → 0.0(記録している上でやっていない=実データ)。
    t = date(2026, 6, 26)
    mem_session.add(GardenDaily(date=date(2026, 6, 25), intensity=1.0, level=1,
                                contributions={"coding": 2.0}, streak_len=1))
    mem_session.flush()
    a = freq_achievement(mem_session, ["reading"], t, window=14, target_days=7)
    assert a == 0.0


def test_flatten_atlas_scores_recurses():
    tree = {
        "key": "total", "score": 60.0, "children": [
            {"key": "economy", "score": 40.0, "children": [
                {"key": "wealth_index", "score": 15.0, "children": []},
                {"key": "savings_rate", "score": None, "children": []},
            ]},
            {"key": "condition", "score": 80.0, "children": [
                {"key": "sleep", "score": 90.0, "children": []},
            ]},
        ],
    }
    flat = flatten_atlas_scores(tree)
    assert flat["total"] == 60.0
    assert flat["wealth_index"] == 15.0
    assert flat["savings_rate"] is None  # 実データ欠測 → 未計測(None)
    assert flat["sleep"] == 90.0


def test_leaf_achievement_atlas_signal_pulls_real_score(mem_session):
    atlas = {"wealth_index": 15.0, "savings_rate": None, "load": 72.0}
    # atlas:<key> は全体マップの実データ score をそのまま返す。
    assert leaf_achievement(mem_session, "atlas:wealth_index", date(2026, 6, 26),
                            14, 7, None, atlas) == 15.0
    assert leaf_achievement(mem_session, "atlas:load", date(2026, 6, 26),
                            14, 7, None, atlas) == 72.0
    # 欠測(None)や未知キーは未計測。
    assert leaf_achievement(mem_session, "atlas:savings_rate", date(2026, 6, 26),
                            14, 7, None, atlas) is None
    assert leaf_achievement(mem_session, "atlas:unknown", date(2026, 6, 26),
                            14, 7, None, atlas) is None


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
