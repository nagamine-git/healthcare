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


def test_insufficient_when_one_group_too_small():
    # 口テープ: 外した夜が 2 夜だけ (< MIN_GROUP=3) → 判定不能。
    rows = [_night(i, mouth_tape=True, sleep_score=80) for i in range(8)]
    rows += [_night(i + 100, mouth_tape=False, sleep_score=70) for i in range(2)]
    res = _analyze_rows(rows)
    tape = _find(res, "mouth_tape")
    assert tape["verdict"] == "insufficient"
    assert tape["primary"] is None
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
