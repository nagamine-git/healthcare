"""羅針盤の重みは「優先度」— 総合点と並び順にだけ効かせる。

⚠️ 各ドメインのスコアは素のまま。ドメインのスコアは「目標にどれだけ近いか」という
客観的な量で、そこに主観の優先度を掛けると、実態が変わっていないのに優先度を
変えただけで数字が動き、推移グラフが意味を失う。
"""

from __future__ import annotations

from app.scoring.atlas import _apply_weights_to_root


def _tree(children):
    return {"key": "root", "score": None, "children": children}


def _c(key, score, weight):
    return {"key": key, "score": score, "weight": weight, "children": []}


def test_domain_scores_stay_raw():
    t = _tree([_c("body", 84.0, 2.0), _c("economy", 14.0, 1.5)])
    _apply_weights_to_root(t)
    assert {c["key"]: c["score"] for c in t["children"]} == {"body": 84.0, "economy": 14.0}


def test_root_uses_weighted_average_and_reports_both():
    t = _tree([_c("a", 100.0, 3.0), _c("b", 0.0, 1.0)])
    _apply_weights_to_root(t)
    assert t["score_weighted"] == 75.0    # (100*3 + 0*1) / 4
    assert t["score_unweighted"] == 50.0  # 素の平均


def test_zero_weight_is_excluded_not_counted_as_zero():
    """重み0は「今は対象外」。0点として総合点を引きずり下ろさない。"""
    t = _tree([_c("a", 80.0, 1.0), _c("ignored", 0.0, 0.0)])
    _apply_weights_to_root(t)
    assert t["score_weighted"] == 80.0
    assert t["score_unweighted"] == 80.0


def test_order_is_headroom_times_priority():
    """並びは「伸びしろ × 優先度」順 = 次に手をつける価値が高い順。

    スコア昇順だけだと、優先度の低いドメインが先頭に来てしまう。
    """
    t = _tree([
        _c("low_prio_far", 10.0, 0.5),   # 伸びしろ90 × 0.5 = 45
        _c("high_prio_mid", 50.0, 2.0),  # 伸びしろ50 × 2.0 = 100
    ])
    _apply_weights_to_root(t)
    assert [c["key"] for c in t["children"]] == ["high_prio_mid", "low_prio_far"]


def test_scoreless_children_go_last():
    t = _tree([_c("none", None, 2.0), _c("has", 50.0, 1.0)])
    _apply_weights_to_root(t)
    assert [c["key"] for c in t["children"]] == ["has", "none"]
