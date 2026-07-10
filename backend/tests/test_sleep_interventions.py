"""就寝前介入の効果分析 (_analyze_rows) の単体テスト。DB 非依存。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.scoring.sleep_interventions import _analyze_rows


def _night(i: int, **kw: Any) -> dict[str, Any]:
    """i 日目の夜の行。指定外のアウトカムは None、介入は未指定なら None。"""
    row: dict[str, Any] = {
        "date": date(2026, 1, 1) + timedelta(days=i),
        "sleep_score": None, "efficiency": None, "deep_min": None, "hrv_overnight": None,
        "earplugs": None, "eyemask": None, "nose_strip": None, "mouth_tape": None,
    }
    row.update(kw)
    return row


def _find(res: dict[str, Any], key: str) -> dict[str, Any]:
    return next(iv for iv in res["interventions"] if iv["key"] == key)


def test_accumulating_below_min_nights():
    rows = [_night(i, earplugs=True, sleep_score=80) for i in range(4)]
    res = _analyze_rows(rows)
    assert res["status"] == "accumulating"
    assert res["remaining"] == 2  # _MIN_NIGHTS(6) - 4


def test_clear_improvement_is_strong_and_improves():
    # 耳栓ありの夜は高スコア、なしの夜は低スコア。差は明白。
    rows: list[dict[str, Any]] = []
    for i in range(8):
        rows.append(_night(i, earplugs=True, sleep_score=85 + (i % 3)))
    for i in range(8, 16):
        rows.append(_night(i, earplugs=False, sleep_score=60 + (i % 3)))
    res = _analyze_rows(rows)
    assert res["status"] == "analyzed"
    ear = _find(res, "earplugs")
    assert ear["n_did"] == 8 and ear["n_didnt"] == 8
    assert ear["verdict"] == "improves"
    assert ear["primary"] is not None
    assert ear["primary"]["outcome"] == "sleep_score"
    assert ear["primary"]["diff"] > 0
    assert ear["primary"]["tier"] in ("strong", "suggestive")


def test_no_effect_when_groups_overlap():
    # 着けた/外したで分布が同じ = 効果なし。
    scores = [70, 72, 68, 71, 69, 73, 70, 71]
    rows: list[dict[str, Any]] = []
    for i, sc in enumerate(scores):
        rows.append(_night(i, eyemask=True, sleep_score=sc))
    for i, sc in enumerate(scores):
        rows.append(_night(i + 100, eyemask=False, sleep_score=sc))
    res = _analyze_rows(rows)
    eye = _find(res, "eyemask")
    assert eye["verdict"] == "no_effect"


def test_insufficient_but_preliminary_when_one_group_small():
    # 口テープ: 外した夜が 2 夜 (< MIN_GROUP=3) → 確定はできない (verdict=insufficient) が、
    # 各群 >=2 あるので暫定シグナル (方向+効果量) は出す。
    rows = [_night(i, mouth_tape=True, sleep_score=80) for i in range(8)]
    rows += [_night(i + 100, mouth_tape=False, sleep_score=70) for i in range(2)]
    res = _analyze_rows(rows)
    tape = _find(res, "mouth_tape")
    assert tape["verdict"] == "insufficient"  # 有意性は主張しない
    assert tape["primary"] is not None         # だが暫定シグナルは提示
    assert tape["primary"]["tier"] == "preliminary"
    assert tape["primary"]["direction"] == "改善" and tape["primary"]["diff"] > 0
    assert tape["n_did"] == 8 and tape["n_didnt"] == 2


def test_suggestion_drop_always_worn():
    # 耳栓を毎晩着けている (外した夜ゼロ) → 「外して検証」を提案。
    rows = [_night(i, earplugs=True, sleep_score=80) for i in range(8)]
    res = _analyze_rows(rows)
    assert res["suggestion"] is not None
    assert "耳栓" in res["suggestion"]["text"]
    assert "外して" in res["suggestion"]["text"]


def test_suggestion_isolate_confounded_pair():
    # 耳栓とアイマスクを必ずセットで着脱 (不一致夜ゼロ) → 「一方だけ」を提案。
    rows: list[dict[str, Any]] = []
    for i in range(8):
        rows.append(_night(i, earplugs=True, eyemask=True, sleep_score=82))
    for i in range(8, 16):
        rows.append(_night(i, earplugs=False, eyemask=False, sleep_score=70))
    res = _analyze_rows(rows)
    assert res["suggestion"] is not None
    txt = res["suggestion"]["text"]
    assert "耳栓" in txt and "アイマスク" in txt
    assert "一方だけ" in txt


# ===== 小サンプル暫定シグナル + 今夜の探索/活用 (B1/B2) =====


def test_preliminary_signal_below_min_group():
    # 各群 2 夜ずつ (< MIN_GROUP=3)。深睡眠の方向と効果量を暫定で出す。
    rows = [_night(i, earplugs=True, deep_min=95) for i in range(2)]
    rows += [_night(i + 100, earplugs=False, deep_min=60) for i in range(2)]
    res = _analyze_rows(rows)
    assert res["status"] == "preliminary"
    ear = _find(res, "earplugs")
    deep = next(o for o in ear["outcomes"] if o["outcome"] == "deep_min")
    assert deep["tier"] == "preliminary"
    assert deep["direction"] == "改善" and deep["diff"] > 0
    assert deep["n_did"] == 2 and deep["n_didnt"] == 2
    # 暫定は確定させない (exploit 対象にしない)
    assert ear["verdict"] == "insufficient"


def test_preliminary_promotes_to_powered_when_data_grows():
    # 各群 4 夜・n=8 → 深睡眠 outcome は preliminary ではなく従来 tier に昇格。
    rows = [_night(i, earplugs=True, deep_min=95 + (i % 3)) for i in range(4)]
    rows += [_night(i + 100, earplugs=False, deep_min=55 + (i % 3)) for i in range(4)]
    res = _analyze_rows(rows)
    assert res["status"] == "analyzed"
    ear = _find(res, "earplugs")
    deep = next(o for o in ear["outcomes"] if o["outcome"] == "deep_min")
    assert deep["tier"] != "preliminary"
    assert deep["q"] is not None  # powered なので FDR q を持つ


def test_tonight_explore_on_from_night_one():
    # ログ皆無 → 夜1から「今夜1条件を試す」データ収集提案。
    res = _analyze_rows([])
    assert res["suggestion"] is not None
    assert res["suggestion"]["kind"] == "explore"
    assert "つけて" in res["suggestion"]["text"]


def test_tonight_exploit_keeps_proven_winner():
    # 口テープが実証済み (improves)・交絡なし・偏りなし → 継続 (exploit) を勧める。
    rows = [_night(i, mouth_tape=True, sleep_score=85 + (i % 3)) for i in range(8)]
    rows += [_night(i + 100, mouth_tape=False, sleep_score=60 + (i % 3)) for i in range(8)]
    res = _analyze_rows(rows)
    tape = _find(res, "mouth_tape")
    assert tape["verdict"] == "improves"
    assert res["suggestion"]["kind"] == "exploit"
    assert "口テープ" in res["suggestion"]["text"]


def test_tonight_deconfound_takes_priority():
    # 常に同時使用の 2 介入 → 交絡崩しが最優先 (exploit より上)。
    rows = [_night(i, earplugs=True, eyemask=True, sleep_score=85) for i in range(8)]
    rows += [_night(i + 100, earplugs=False, eyemask=False, sleep_score=62) for i in range(8)]
    res = _analyze_rows(rows)
    assert res["suggestion"]["kind"] == "deconfound"
    assert "一方だけ" in res["suggestion"]["text"]
