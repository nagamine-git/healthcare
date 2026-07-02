"""就寝前の介入 (耳栓/アイマスク/鼻ストリップ/口テープ) の n-of-1 効果分析。

各介入を「着けた夜 (True) vs 外した夜 (False)」の 2 群に分け、睡眠アウトカム
(睡眠スコア/効率/深睡眠/夜間HRV) の平均差を並べ替え検定で評価する。全 (介入×アウトカム) を
BH-FDR で多重補正。手法は sleep_drivers / migraine_stats と共通だが、二値介入なので中央値分割
ではなく実際の着脱で群を作る点が異なる (だから専用モジュール)。

「ハイブリッド運用」の要: 複数介入が交絡して各効果を分離できない状況 (毎晩着けている / 常に同時に
着けている) を検知し、「今夜は◯◯だけ外して検証」といった切り分けを提案する。
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from app.db import session_scope
from app.models import SleepInterventionLog, SleepSession
from app.scoring.migraine_stats import benjamini_hochberg, permutation_test
from app.scoring.timewindow import app_today

_DAYS = 120        # 解析窓 (日)
_MIN_NIGHTS = 6    # これ未満の記録夜数なら「蓄積中」表示
_MIN_GROUP = 3     # 着けた/外した 各群の最小数 (未満は検定しない)
FDR_Q = 0.05

# 介入 (key, ラベル)
INTERVENTIONS: list[tuple[str, str]] = [
    ("earplugs", "耳栓"),
    ("eyemask", "アイマスク"),
    ("nose_strip", "ノーズブリーズ"),
    ("mouth_tape", "口テープ"),
]
# アウトカム (すべて「高いほど良い」)。先頭 = 見出し判定に使う主指標。
OUTCOMES: list[tuple[str, str]] = [
    ("sleep_score", "睡眠スコア"),
    ("efficiency", "睡眠効率"),
    ("deep_min", "深睡眠"),
    ("hrv_overnight", "夜間HRV"),
]
_PRIMARY = OUTCOMES[0][0]


def _collect(target: date_type) -> list[dict[str, Any]]:
    """SleepSession と介入ログが両方ある夜の行 (アウトカム + 介入フラグ) を返す。"""
    start = target - timedelta(days=_DAYS)
    with session_scope() as s:
        sleeps = {
            r.date: r
            for r in s.execute(
                select(SleepSession).where(
                    SleepSession.date >= start, SleepSession.date <= target
                )
            ).scalars()
        }
        logs = {
            r.date: r
            for r in s.execute(
                select(SleepInterventionLog).where(
                    SleepInterventionLog.date >= start,
                    SleepInterventionLog.date <= target,
                )
            ).scalars()
        }
        rows: list[dict[str, Any]] = []
        for d, log in logs.items():
            sl = sleeps.get(d)
            if sl is None:
                continue  # その夜の睡眠データがまだ無い → アウトカム不明
            if all(
                getattr(log, f) is None
                for f in ("earplugs", "eyemask", "nose_strip", "mouth_tape")
            ):
                continue  # 全項目 未記録の空行は夜数に数えない
            total, awake = sl.total_min, sl.awake_min
            eff = (
                total / (total + awake) * 100
                if (total and awake is not None and (total + awake) > 0)
                else None
            )
            rows.append({
                "date": d,
                # outcomes
                "sleep_score": sl.sleep_score,
                "efficiency": eff,
                "deep_min": sl.deep_min,
                "hrv_overnight": sl.hrv_overnight_avg,
                # interventions (True/False/None)
                "earplugs": log.earplugs,
                "eyemask": log.eyemask,
                "nose_strip": log.nose_strip,
                "mouth_tape": log.mouth_tape,
            })
    return rows


def _tier(p: float, q: float) -> str:
    if q < FDR_Q:
        return "strong"
    if p < 0.1:
        return "suggestive"
    if p < 0.25:
        return "trend"
    return "weak"


def _analyze_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """DB 非依存の純関数。行 (アウトカム + 介入フラグ) から効果分析を組み立てる。"""
    n = len(rows)
    base: dict[str, Any] = {"n_nights": n, "interventions": [], "suggestion": None}
    if n < _MIN_NIGHTS:
        base["status"] = "accumulating"
        base["remaining"] = _MIN_NIGHTS - n
        return base

    # 全 (介入×アウトカム) を検定 → まとめて FDR。
    tests: list[dict[str, Any]] = []
    for ikey, _ilabel in INTERVENTIONS:
        for okey, olabel in OUTCOMES:
            did = [r[okey] for r in rows if r.get(ikey) is True and r.get(okey) is not None]
            didnt = [r[okey] for r in rows if r.get(ikey) is False and r.get(okey) is not None]
            if len(did) < _MIN_GROUP or len(didnt) < _MIN_GROUP:
                continue
            p, diff = permutation_test(did, didnt)
            if p is None or diff is None:
                continue
            tests.append({
                "intervention": ikey, "outcome": okey, "outcome_label": olabel,
                "p": round(p, 4), "diff": diff,
            })

    qmap: dict[tuple[str, str], float] = {}
    if tests:
        qs = benjamini_hochberg([t["p"] for t in tests])
        for t, q in zip(tests, qs, strict=True):
            qmap[(t["intervention"], t["outcome"])] = q

    for ikey, ilabel in INTERVENTIONS:
        # 群サイズはアウトカム欠測に依存しないよう、記録された True/False 夜数で数える
        n_did = sum(1 for r in rows if r.get(ikey) is True)
        n_didnt = sum(1 for r in rows if r.get(ikey) is False)
        outcomes: list[dict[str, Any]] = []
        for t in tests:
            if t["intervention"] != ikey:
                continue
            q = qmap[(ikey, t["outcome"])]
            tier = _tier(t["p"], q)
            outcomes.append({
                "outcome": t["outcome"], "outcome_label": t["outcome_label"],
                "diff": round(t["diff"], 1), "p": t["p"], "q": round(q, 4), "tier": tier,
                "direction": "改善" if t["diff"] > 0 else "悪化",
            })
        primary = next((o for o in outcomes if o["outcome"] == _PRIMARY), None)
        if primary is None:
            verdict = "insufficient"
        elif primary["tier"] in ("strong", "suggestive") and primary["diff"] > 0:
            verdict = "improves"
        elif primary["tier"] in ("strong", "suggestive") and primary["diff"] < 0:
            verdict = "worsens"
        else:
            verdict = "no_effect"
        # 見出しは主指標順、その後 tier の強い順
        outcomes.sort(key=lambda o: (o["outcome"] != _PRIMARY, o["q"]))
        base["interventions"].append({
            "key": ikey, "label": ilabel,
            "n_did": n_did, "n_didnt": n_didnt,
            "verdict": verdict, "primary": primary, "outcomes": outcomes,
        })

    base["suggestion"] = _suggestion(rows, base["interventions"])
    base["status"] = "analyzed"
    base["reliability"] = "high" if n >= 45 else ("medium" if n >= 21 else "low")
    return base


def _suggestion(
    rows: list[dict[str, Any]], interventions: list[dict[str, Any]]
) -> dict[str, str] | None:
    """交絡を崩す「今夜の検証」を最大1件提案 (ハイブリッド運用の核)。"""
    label = {k: v for k, v in INTERVENTIONS}

    # (a) ほぼ毎晩着けている介入 (外した夜が不足) → 今夜は外して検証。
    #     効果未確定 (verdict=insufficient/no_effect) のものを優先。
    undecided = {
        iv["key"] for iv in interventions if iv["verdict"] in ("insufficient", "no_effect")
    }
    always_on = [
        iv for iv in interventions
        if iv["n_didnt"] < _MIN_GROUP and iv["n_did"] >= _MIN_GROUP
    ]
    always_on.sort(key=lambda iv: (iv["key"] not in undecided, iv["n_didnt"]))
    if always_on:
        iv = always_on[0]
        return {
            "text": f"今夜は{iv['label']}を外して寝てみる",
            "reason": (
                f"{iv['label']}を外した夜が{iv['n_didnt']}夜しかなく、効果を判定できません。"
                "着けない夜を作ると比較できます。"
            ),
        }

    # (b) 2 介入がほぼ常に同時 (着ける/外すが一致しすぎ) → 今夜は一方だけ。
    keys = [k for k, _ in INTERVENTIONS]
    best: tuple[int, str, str] | None = None  # (不一致夜数, keyA, keyB)
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a, b = keys[i], keys[j]
            both = [r for r in rows if r.get(a) is not None and r.get(b) is not None]
            if len(both) < _MIN_NIGHTS:
                continue
            discordant = sum(1 for r in both if r[a] != r[b])
            # 両方とも「着ける寄り」で不一致が乏しい = 効果を切り分けられない
            a_on = sum(1 for r in both if r[a] is True)
            b_on = sum(1 for r in both if r[b] is True)
            if discordant < _MIN_GROUP and a_on >= _MIN_GROUP and b_on >= _MIN_GROUP:
                if best is None or discordant < best[0]:
                    best = (discordant, a, b)
    if best is not None:
        _, a, b = best
        return {
            "text": f"今夜は{label[a]}と{label[b]}のどちらか一方だけにする",
            "reason": (
                f"{label[a]}と{label[b]}をほぼ毎晩セットで使っているため、"
                "どちらが効いているか分離できません。片方だけの夜を作ると切り分けられます。"
            ),
        }
    return None


def analyze(target: date_type | None = None) -> dict[str, Any]:
    target = target or app_today()
    return _analyze_rows(_collect(target))
