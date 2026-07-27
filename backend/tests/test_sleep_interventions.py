"""就寝前介入の効果分析 (_analyze_rows) の単体テスト。DB 非依存。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.scoring.sleep_interventions import _MIN_STD_EFFECT, _analyze_rows


def _night(i: int, **kw: Any) -> dict[str, Any]:
    """i 日目の夜の行。指定外のアウトカムは None、介入は未指定なら None。"""
    row: dict[str, Any] = {
        "date": date(2026, 1, 1) + timedelta(days=i),
        "sleep_score": None, "efficiency": None, "deep_min": None, "hrv_overnight": None,
        "earplugs": None, "eyemask": None, "nose_strip": None, "mouth_tape": None,
        "breathing": None, "meditation": None,
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


# ===== breathing / meditation の n-of-1 格上げ (2026-07-24 design Step3) =====


def test_breathing_and_meditation_are_analyzed():
    # 呼吸法・瞑想は既存4フラグと完全に同格に扱われる: 十分な夜数があれば analyzed/improves になる。
    rows: list[dict[str, Any]] = []
    for i in range(8):
        rows.append(_night(i, breathing=True, meditation=True, sleep_score=85 + (i % 3)))
    for i in range(8, 16):
        rows.append(_night(i, breathing=False, meditation=False, sleep_score=60 + (i % 3)))
    res = _analyze_rows(rows)
    assert res["status"] == "analyzed"

    breathing = _find(res, "breathing")
    assert breathing["n_did"] == 8 and breathing["n_didnt"] == 8
    assert breathing["verdict"] == "improves"
    assert breathing["primary"] is not None
    assert breathing["primary"]["outcome"] == "sleep_score"
    assert breathing["primary"]["diff"] > 0

    meditation = _find(res, "meditation")
    assert meditation["n_did"] == 8 and meditation["n_didnt"] == 8
    assert meditation["verdict"] == "improves"
    assert meditation["primary"] is not None
    assert meditation["primary"]["outcome"] == "sleep_score"
    assert meditation["primary"]["diff"] > 0


def test_breathing_only_night_is_not_dropped_as_empty_row():
    # 旧実装の穴: _collect の空行判定が4フラグしか見ておらず、breathing だけ記録した夜が
    # 「全項目未記録」扱いで捨てられていた。_analyze_rows レベルでは breathing/meditation を
    # 単独指定した夜もちゃんと群にカウントされることを確認する。
    rows = [_night(i, breathing=True, sleep_score=80) for i in range(4)]
    rows += [_night(i + 100, breathing=False, sleep_score=65) for i in range(4)]
    res = _analyze_rows(rows)
    breathing = _find(res, "breathing")
    assert breathing["n_did"] == 4 and breathing["n_didnt"] == 4


def test_meditation_in_explore_order_gets_tonight_suggestion():
    # 瞑想が一度も記録されていない (ログ皆無) → 夜1からの探索提案に breathing/meditation も候補になり得る。
    res = _analyze_rows([])
    assert res["suggestion"] is not None
    assert res["suggestion"]["kind"] == "explore"


# ===== worth_verifying (「確かめる価値があるもの」): 効果量 (標準化) × データの薄さ =====


def test_worth_verifying_empty_when_no_candidates():
    # 記録なし → 候補になりうる (介入×アウトカム) が存在しない → 空配列。
    res = _analyze_rows([])
    assert res["worth_verifying"] == []


def test_worth_verifying_picks_large_effect_thin_data():
    # nose_strip → deep_min を模した実データ相当のケース: 効果量が大きく (標準化効果量>=1)、
    # 着けた夜が少ない (5夜) のに対し外した夜は多い (13夜)。p はギリギリ 0.05 を超える程度に
    # overlap させ、q (このケースは powered な検定がこれ1件のみなので q=p) が strong の
    # 閾値 (<0.05) を割らないようにする (=strong に昇格させない)。
    did_vals = [65, 71, 59, 73, 67]  # 5夜
    didnt_vals = [70, 75, 65, 80, 72, 68, 78, 74, 66, 76, 71, 69, 77]  # 13夜
    rows: list[dict[str, Any]] = []
    for i, v in enumerate(did_vals):
        rows.append(_night(i, nose_strip=True, deep_min=v))
    for i, v in enumerate(didnt_vals):
        rows.append(_night(i + 100, nose_strip=False, deep_min=v))
    res = _analyze_rows(rows)
    nose = _find(res, "nose_strip")
    deep = next(o for o in nose["outcomes"] if o["outcome"] == "deep_min")
    assert deep["tier"] != "strong"  # まだ確定していないケースを検証しているか確認
    assert deep["n_did"] == 5 and deep["n_didnt"] == 13

    wv = res["worth_verifying"]
    assert len(wv) >= 1
    top = wv[0]
    assert top["key"] == "nose_strip"
    assert top["outcome"] == "deep_min"
    assert top["n_did"] == 5 and top["n_didnt"] == 13
    assert "少数例では効果が大きく出やすい" in top["reason"]


def test_worth_verifying_excludes_small_effect_thick_data():
    # 就寝時刻の乱れ的なケースを模す: 効果量はごく小さい (diff 小・SD 大) が n=82 と厚い。
    # 標準化効果量が小さいので候補から除外されるべき (効果が確定していなくても検証の価値は薄い)。
    import random

    rng = random.Random(42)
    did_vals = [70 + rng.uniform(-10, 10) for _ in range(41)]
    didnt_vals = [69.2 + rng.uniform(-10, 10) for _ in range(41)]  # diff は小さい, SD は大きい
    rows: list[dict[str, Any]] = []
    for i, v in enumerate(did_vals):
        rows.append(_night(i, earplugs=True, efficiency=v))
    for i, v in enumerate(didnt_vals):
        rows.append(_night(i + 200, earplugs=False, efficiency=v))
    res = _analyze_rows(rows)
    ear = _find(res, "earplugs")
    eff = next(o for o in ear["outcomes"] if o["outcome"] == "efficiency")
    assert eff["tier"] != "strong"  # 前提確認: strong 昇格による除外ではなく効果量による除外を見る
    assert eff["n_did"] == 41 and eff["n_didnt"] == 41

    keys = [(w["key"], w["outcome"]) for w in res["worth_verifying"]]
    assert ("earplugs", "efficiency") not in keys


def test_worth_verifying_excludes_strong_tier():
    # 明確な差 (耳栓あり/なしで sleep_score が完全に分離) → strong に確定するはず。
    # strong はもう結論が出ているので worth_verifying の対象外。
    rows: list[dict[str, Any]] = []
    for i in range(10):
        rows.append(_night(i, earplugs=True, sleep_score=90 + (i % 3)))
    for i in range(10, 20):
        rows.append(_night(i, earplugs=False, sleep_score=40 + (i % 3)))
    res = _analyze_rows(rows)
    ear = _find(res, "earplugs")
    primary = ear["primary"]
    assert primary["tier"] == "strong"  # 前提確認: このケースは strong になる

    keys = [(w["key"], w["outcome"]) for w in res["worth_verifying"]]
    assert ("earplugs", "sleep_score") not in keys


def test_worth_verifying_normalizes_across_outcome_units():
    # アウトカムごとに単位・散らばりが違う: sleep_score (0-100点、ばらつき大) と
    # deep_min (分、ばらつき小)。生の diff だけを比べると sleep_score 側の方が大きいのに、
    # 標準化効果量で見ると deep_min 側の方が大きく逆転する ── これが「単位で判定しない」
    # 正規化の効果を示す。
    rows: list[dict[str, Any]] = []
    # earplugs: sleep_score の生 diff は大きい (約9点) が、ばらつきも大きく標準化効果量は小さい
    scores_did = [80, 60, 90, 70, 95, 65]
    scores_didnt = [74, 54, 84, 64, 89, 40]
    for i, v in enumerate(scores_did):
        rows.append(_night(i, earplugs=True, sleep_score=v))
    for i, v in enumerate(scores_didnt):
        rows.append(_night(i + 100, earplugs=False, sleep_score=v))
    # mouth_tape: deep_min の生 diff は小さい (約4分) が、ばらつきが小さく標準化効果量は大きい
    deep_did = [63, 65, 62, 64, 68, 61]
    deep_didnt = [60, 58, 61, 59, 64, 57]
    for i, v in enumerate(deep_did):
        rows.append(_night(i + 200, mouth_tape=True, deep_min=v))
    for i, v in enumerate(deep_didnt):
        rows.append(_night(i + 300, mouth_tape=False, deep_min=v))
    res = _analyze_rows(rows)

    ear = _find(res, "earplugs")
    ear_score = next(o for o in ear["outcomes"] if o["outcome"] == "sleep_score")
    tape = _find(res, "mouth_tape")
    tape_deep = next(o for o in tape["outcomes"] if o["outcome"] == "deep_min")

    # 生の diff は sleep_score 側の方が大きいのに、標準化効果量は deep_min 側の方が大きい (逆転)
    assert abs(ear_score["diff"]) > abs(tape_deep["diff"])
    assert ear_score["std_effect"] is not None and tape_deep["std_effect"] is not None
    assert tape_deep["std_effect"] > ear_score["std_effect"]
    assert ear_score["std_effect"] < _MIN_STD_EFFECT <= tape_deep["std_effect"]
    assert tape_deep["tier"] != "strong"  # 前提確認: 除外は effect size 基準であって strong ではない

    keys = [(w["key"], w["outcome"]) for w in res["worth_verifying"]]
    assert ("mouth_tape", "deep_min") in keys
    assert ("earplugs", "sleep_score") not in keys


def test_worth_verifying_capped_at_three():
    # 4つの (介入×アウトカム) が全部候補条件を満たしても、上位3件までしか出さない。
    # (同一の did/didnt パターンを4介入に適用 = 同一 p なので BH 補正後も全て非 strong で揃う)
    rows: list[dict[str, Any]] = []
    pairs = ["earplugs", "eyemask", "nose_strip", "mouth_tape"]
    did_vals = [65, 71, 59, 73, 67]
    didnt_vals = [70, 75, 65, 80, 72, 68, 78, 74, 66, 76, 71, 69, 77]
    for idx, ikey in enumerate(pairs):
        for i, v in enumerate(did_vals):
            rows.append(_night(idx * 1000 + i, sleep_score=v, **{ikey: True}))
        for i, v in enumerate(didnt_vals):
            rows.append(_night(idx * 1000 + i + 100, sleep_score=v, **{ikey: False}))
    res = _analyze_rows(rows)
    for iv in res["interventions"]:
        primary = iv.get("primary")
        assert primary is not None and primary["tier"] != "strong"  # 前提: 全件 strong ではない
    assert len(res["worth_verifying"]) == 3  # 4件条件を満たすが上限3件に切り詰められる


def test_tonight_plan_prefers_larger_effect_when_coverage_tied():
    # explore-on: eyemask と nose_strip がともに未検証 (n_did=2 で同点タイ)。
    # 固定優先順 (_EXPLORE_ORDER) では eyemask の方が先だが、nose_strip の方が
    # (暫定段階でも) 標準化効果量が明らかに大きいので、そちらを優先して提案するべき。
    # 他の介入 (earplugs/mouth_tape/breathing/meditation) は両群十分なデータ (no_effect)
    # にして on/off どちらの候補にもならないようにし、eyemask vs nose_strip の一騎打ちにする。
    rows: list[dict[str, Any]] = []
    no_effect_did = [70, 72, 68, 71]
    no_effect_didnt = [71, 69, 73, 70]
    for j, key in enumerate(["earplugs", "mouth_tape", "breathing", "meditation"]):
        for i, v in enumerate(no_effect_did):
            rows.append(_night(j * 100 + i, sleep_score=v, **{key: True}))
        for i, v in enumerate(no_effect_didnt):
            rows.append(_night(j * 100 + i + 10, sleep_score=v, **{key: False}))
    # eyemask: ほぼ差がない (効果量小)
    rows.append(_night(1000, eyemask=True, sleep_score=70))
    rows.append(_night(1001, eyemask=True, sleep_score=71))
    rows.append(_night(1002, eyemask=False, sleep_score=70))
    rows.append(_night(1003, eyemask=False, sleep_score=71))
    # nose_strip: 差が大きい (効果量大)
    rows.append(_night(1004, nose_strip=True, sleep_score=95))
    rows.append(_night(1005, nose_strip=True, sleep_score=96))
    rows.append(_night(1006, nose_strip=False, sleep_score=40))
    rows.append(_night(1007, nose_strip=False, sleep_score=41))
    res = _analyze_rows(rows)
    assert res["suggestion"]["kind"] == "explore"
    assert "ノーズブリーズ" in res["suggestion"]["text"]
