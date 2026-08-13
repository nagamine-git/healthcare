"""布団 (寝具) の記録と one-vs-rest 分析。"""

from __future__ import annotations

from datetime import date, timedelta

from app.models import SleepInterventionLog, SleepSession
from app.scoring.sleep_interventions import _analyze_bedding, _collect

TARGET = date(2026, 8, 10)


def _seed(session, *, nights: list[tuple[int, str | None, float]]) -> None:
    """(何日前, 布団名, 睡眠スコア) の夜を仕込む。"""
    for days_ago, bedding, score in nights:
        d = TARGET - timedelta(days=days_ago)
        session.add(SleepSession(
            date=d, source="garmin", total_min=400, deep_min=60, rem_min=80,
            awake_min=10, sleep_score=score))
        session.add(SleepInterventionLog(date=d, earplugs=False, bedding=bedding))
    session.commit()


def test_one_vs_rest_compares_each_bedding(db_engine, session):
    """布団ごとに「その布団 vs 記録がある他の布団」で比較する。"""
    _seed(session, nights=[
        (1, "羽毛", 85), (2, "羽毛", 82), (3, "羽毛", 88), (4, "羽毛", 84),
        (5, "せんべい", 60), (6, "せんべい", 65), (7, "せんべい", 58), (8, "せんべい", 62),
    ])
    out = _analyze_bedding(_collect(TARGET))

    assert out["n_nights"] == 8
    names = [b["name"] for b in out["beddings"]]
    assert set(names) == {"羽毛", "せんべい"}
    futon = next(b for b in out["beddings"] if b["name"] == "羽毛")
    primary = next(o for o in futon["outcomes"] if o["outcome"] == "sleep_score")
    assert primary["diff"] > 0          # 羽毛の夜のほうがスコアが高い
    assert primary["n_with"] == 4 and primary["n_without"] == 4
    assert futon["verdict"] in ("improves", "insufficient")  # n=4 なので tier 次第


def test_unrecorded_nights_do_not_pollute_the_control(db_engine, session):
    """未記録の夜は「別の布団」ではなく「わからない」— 対照群に混ぜない。"""
    _seed(session, nights=[
        (1, "羽毛", 85), (2, "羽毛", 82), (3, "羽毛", 88),
        (4, "せんべい", 60), (5, "せんべい", 65),
        (6, None, 10), (7, None, 5),  # 未記録のひどい夜 (混ざれば diff が跳ね上がる)
    ])
    out = _analyze_bedding(_collect(TARGET))

    assert out["n_nights"] == 5  # 未記録2夜は数えない
    futon = next(b for b in out["beddings"] if b["name"] == "羽毛")
    primary = next(o for o in futon["outcomes"] if o["outcome"] == "sleep_score")
    # 対照が「せんべい」だけなら diff は 85-62.5 ≈ +22.5 程度。
    # 未記録が混ざると +40 超になる — そうなっていないこと。
    assert primary["n_without"] == 2
    assert primary["diff"] < 30


def test_single_bedding_has_no_comparison(db_engine, session):
    """1種類しか記録が無ければ比較しない (差は定義できない)。"""
    _seed(session, nights=[(1, "羽毛", 85), (2, "羽毛", 82)])
    out = _analyze_bedding(_collect(TARGET))

    assert out["beddings"][0]["verdict"] == "insufficient"
    assert out["beddings"][0]["outcomes"] == []
    assert "2種類以上" in out["note"]
