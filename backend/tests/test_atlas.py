from __future__ import annotations

from datetime import date, datetime

from app.db import session_scope
from app.models.health import HealthCheckup, WeightSample
from app.scoring.atlas import build_atlas


def _leaves(node, out=None):
    out = out if out is not None else {}
    out[node["key"]] = node
    for c in node["children"]:
        _leaves(c, out)
    return out


def test_build_atlas_empty_db_does_not_raise(db_engine):
    with session_scope() as session:
        tree = build_atlas(session)
    assert tree["key"] == "total"
    keys = _leaves(tree)
    # 主要ドメインが揃う
    assert {"condition", "body", "fitness", "checkup"} <= set(keys)
    # データ無しでも例外を出さず current は None
    assert keys["weight"]["current"] is None


def test_body_leaf_has_current_median_target(db_engine, monkeypatch):
    # 身長・年齢・性別を既定(config)で解決し、体重/体脂肪を入れる
    with session_scope() as session:
        session.add(WeightSample(ts=datetime(2026, 6, 17, 21, 0), weight_kg=53.9,
                                 body_fat_pct=17.2, source="hae"))
    with session_scope() as session:
        leaves = _leaves(build_atlas(session))
    bf = leaves["body_fat"]
    assert bf["current"] == 17.2
    assert bf["population"] and "median" in bf["population"]  # 母集団中央値
    assert bf["target"] is not None  # 目標(config)
    assert leaves["weight"]["current"] == 53.9
    # bmi は体型と健診の両ブランチに出る。体型側は身長から算出される。
    with session_scope() as session:
        tree = build_atlas(session)
    body = next(c for c in tree["children"] if c["key"] == "body")
    body_bmi = next(c for c in body["children"] if c["key"] == "bmi")
    assert body_bmi["current"] is not None


def test_domains_have_score_and_estimated_targets(db_engine):
    with session_scope() as session:
        session.add(WeightSample(ts=datetime(2026, 6, 17, 21, 0), weight_kg=53.9,
                                 body_fat_pct=17.2, source="hae"))
    with session_scope() as session:
        tree = build_atlas(session)
    domains = {c["key"]: c for c in tree["children"]}
    # 体型ドメインは子の score 平均から総合点を持つ(閉時表示・レーダー軸に使う)
    assert domains["body"]["score"] is not None
    body = {c["key"]: c for c in domains["body"]["children"]}
    assert body["bmi"]["target"] == 22.0           # 推定目標
    assert body["bmi"]["current"] is not None
    # 体脂肪は明示目標(config)があり score も付く
    assert body["body_fat"]["target"] is not None and body["body_fat"]["score"] is not None


def test_srt_contributes_to_fitness_score(db_engine):
    from app.models.health import FitnessTestResult

    with session_scope() as session:
        session.add(FitnessTestResult(test_key="srt", performed_on=date(2026, 6, 1), value=10.0))
    with session_scope() as session:
        tree = build_atlas(session)
    fitness = next(c for c in tree["children"] if c["key"] == "fitness")
    srt = next(c for c in fitness["children"] if c["key"] == "srt")
    assert srt["score"] == 100.0  # 満点 10/10 → 100点(従来は None で除外されていた)
    assert fitness["score"] is not None


def test_learning_leaf_has_progress_target(db_engine):
    from app.scoring.learning import TOTAL_SECTIONS

    with session_scope() as session:
        tree = build_atlas(session)
    life = next(c for c in tree["children"] if c["key"] == "life")
    learn = next(c for c in life["children"] if c["key"] == "learning_sections")
    assert learn["target"] == float(TOTAL_SECTIONS)  # 全節読了が目標 → 進捗%でスコア化
    assert learn["score"] is not None


def test_checkup_leaf_has_range(db_engine):
    with session_scope() as session:
        session.add(HealthCheckup(date=date(2026, 6, 1),
                                  values=[{"key": "ldl_c", "value": 110, "unit": "mg/dL"}]))
    with session_scope() as session:
        leaves = _leaves(build_atlas(session))
    ldl = leaves["ldl_c"]
    assert ldl["current"] == 110
    assert ldl["population"] and "range" in ldl["population"]
