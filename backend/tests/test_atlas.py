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


def test_learning_leaf_scored_against_today_quota(db_engine):
    # 計画が無い(空DB)ときは全体進捗にフォールバックし、目標・スコアが入る。
    with session_scope() as session:
        tree = build_atlas(session)
    life = next(c for c in tree["children"] if c["key"] == "life")
    learn = next(c for c in life["children"] if c["key"] == "learning")
    assert learn["target"] is not None
    assert learn["score"] is not None


def test_learning_uses_pace_quota_when_plan_exists(db_engine):
    # 目標日のある計画があると、学習は「今日のノルマ達成度」で評価される(全80比の過酷さを回避)。
    import app.scoring.atlas as atlas_mod

    def fake_projection(target):
        return {"done_units": 6, "total_units": 80, "needed_today_min": 2, "needed_today_safe": 4}

    # projection は _learning_leaf 内で import される → モジュール属性を差し替え
    from app.scoring import learning as learning_mod
    orig = learning_mod.projection
    learning_mod.projection = fake_projection
    try:
        with session_scope() as session:
            tree = atlas_mod.build_atlas(session)
    finally:
        learning_mod.projection = orig
    life = next(c for c in tree["children"] if c["key"] == "life")
    learn = next(c for c in life["children"] if c["key"] == "learning")
    assert learn["current"] == 6.0
    assert learn["target"] == 8.0   # 今日のノルマ = done + needed_today_min
    # 6/8 = 75点(全80比の 7.5点 ではない)
    assert learn["score"] == 75.0


def test_checkup_leaf_has_range(db_engine):
    with session_scope() as session:
        session.add(HealthCheckup(date=date(2026, 6, 1),
                                  values=[{"key": "ldl_c", "value": 110, "unit": "mg/dL"}]))
    with session_scope() as session:
        leaves = _leaves(build_atlas(session))
    ldl = leaves["ldl_c"]
    assert ldl["current"] == 110
    assert ldl["population"] and "range" in ldl["population"]


def test_atlas_includes_economy_and_identity(db_engine):
    from app.models.health import AssetHolding
    from app.scoring.finance import get_life_profile

    with session_scope() as session:
        session.add(AssetHolding(name="現金", category="cash", value_jpy=3_000_000, target_weight=0))
        lp = get_life_profile(session)
        lp.debt_balance_jpy = 1_000_000  # 純資産 = 300万 - 100万 = 200万
    with session_scope() as session:
        tree = build_atlas(session)
    keys = _leaves(tree)
    assert "economy" in keys and "identity" in keys  # 資産・羅針盤ブランチが統合
    wi = keys.get("wealth_index")
    assert wi is not None and wi["current"] is not None and wi["current"] > 0  # √(総資産×純資産)
    assert keys["net_worth"]["current"] == 2_000_000
