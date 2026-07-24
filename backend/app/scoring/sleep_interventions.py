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
_MIN_NIGHTS = 6    # これ以上 & 各群>=_MIN_GROUP で「有意性を語れる (powered)」
_MIN_GROUP = 3     # 着けた/外した 各群の最小数 (powered 判定に使用)
_MIN_ARM_PRELIM = 2  # 各群これ以上あれば「暫定シグナル」(方向+効果量) は出す
FDR_Q = 0.05

# 探索 (未検証の介入を今夜試す) の優先順。文献的な堅さ・導入しやすさ順。
_EXPLORE_ORDER = ["earplugs", "mouth_tape", "eyemask", "nose_strip", "breathing", "meditation"]

# 介入 (key, ラベル)
INTERVENTIONS: list[tuple[str, str]] = [
    ("earplugs", "耳栓"),
    ("eyemask", "アイマスク"),
    ("nose_strip", "ノーズブリーズ"),
    ("mouth_tape", "口テープ"),
    ("breathing", "呼吸法"),
    ("meditation", "瞑想"),
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
                for f in ("earplugs", "eyemask", "nose_strip", "mouth_tape", "breathing", "meditation")
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
                "breathing": log.breathing,
                "meditation": log.meditation,
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


def _verdict(primary: dict[str, Any] | None) -> str:
    """主指標から確定 verdict。暫定 (preliminary) は確定させず insufficient 扱い。"""
    if primary is None or primary["tier"] == "preliminary":
        return "insufficient"
    if primary["tier"] in ("strong", "suggestive"):
        return "improves" if primary["diff"] > 0 else "worsens"
    return "no_effect"


def _analyze_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """DB 非依存の純関数。行 (アウトカム + 介入フラグ) から効果分析を組み立てる。

    ハードゲート (n>=_MIN_NIGHTS & 各群>=_MIN_GROUP) 未満でも、各群 >=_MIN_ARM_PRELIM あれば
    「暫定シグナル」(方向 + 効果量 + n) を tier="preliminary" で出す。有意性・因果は主張しない。
    データが育てば同じ枠が strong/suggestive/trend/weak に自動昇格する。
    """
    n = len(rows)
    base: dict[str, Any] = {"n_nights": n, "interventions": [], "suggestion": None}

    # 各 (介入×アウトカム) の観測差を算出 (各群 >=_MIN_ARM_PRELIM)。
    # powered = 各群>=_MIN_GROUP かつ n>=_MIN_NIGHTS。powered のみ FDR 補正して有意性を語る。
    raw: dict[tuple[str, str], dict[str, Any]] = {}
    powered: list[tuple[str, str]] = []
    for ikey, _ilabel in INTERVENTIONS:
        for okey, olabel in OUTCOMES:
            did = [r[okey] for r in rows if r.get(ikey) is True and r.get(okey) is not None]
            didnt = [r[okey] for r in rows if r.get(ikey) is False and r.get(okey) is not None]
            if len(did) < _MIN_ARM_PRELIM or len(didnt) < _MIN_ARM_PRELIM:
                continue
            p, diff = permutation_test(did, didnt)
            if p is None or diff is None:
                continue
            is_powered = len(did) >= _MIN_GROUP and len(didnt) >= _MIN_GROUP and n >= _MIN_NIGHTS
            raw[(ikey, okey)] = {
                "outcome_label": olabel, "p": round(p, 4), "diff": diff,
                "powered": is_powered, "n_did": len(did), "n_didnt": len(didnt),
            }
            if is_powered:
                powered.append((ikey, okey))

    qmap: dict[tuple[str, str], float] = {}
    if powered:
        qs = benjamini_hochberg([raw[k]["p"] for k in powered])
        for k, q in zip(powered, qs, strict=True):
            qmap[k] = q

    for ikey, ilabel in INTERVENTIONS:
        # 群サイズはアウトカム欠測に依存しないよう、記録された True/False 夜数で数える
        n_did = sum(1 for r in rows if r.get(ikey) is True)
        n_didnt = sum(1 for r in rows if r.get(ikey) is False)
        if n_did + n_didnt == 0:
            continue  # 一度も記録の無い介入はパネルに出さない (今夜プランで探索対象にする)
        outcomes: list[dict[str, Any]] = []
        for okey, _olabel in OUTCOMES:
            r = raw.get((ikey, okey))
            if r is None:
                continue
            if r["powered"]:
                q: float | None = round(qmap[(ikey, okey)], 4)
                tier = _tier(r["p"], qmap[(ikey, okey)])
            else:
                q = None
                tier = "preliminary"
            outcomes.append({
                "outcome": okey, "outcome_label": r["outcome_label"],
                "diff": round(r["diff"], 1), "p": r["p"], "q": q, "tier": tier,
                "direction": "改善" if r["diff"] > 0 else "悪化",
                "n_did": r["n_did"], "n_didnt": r["n_didnt"],
            })
        primary = next((o for o in outcomes if o["outcome"] == _PRIMARY), None)
        verdict = _verdict(primary)
        # 主指標を先頭 → powered 優先 → q 昇順 (preliminary は q=None なので末尾寄せ)
        outcomes.sort(key=lambda o: (
            o["outcome"] != _PRIMARY, o["tier"] == "preliminary",
            o["q"] if o["q"] is not None else 1.0,
        ))
        base["interventions"].append({
            "key": ikey, "label": ilabel,
            "n_did": n_did, "n_didnt": n_didnt,
            "verdict": verdict, "primary": primary, "outcomes": outcomes,
        })

    # 介入を確度高い順に並べる: 主指標の q 昇順 (有意なものを先頭)。
    # primary 無し / q 未確定 (preliminary) は末尾に寄せる。
    base["interventions"].sort(key=lambda iv: (
        iv.get("primary") is None,
        iv["primary"]["q"]
        if iv.get("primary") and iv["primary"].get("q") is not None
        else 1.0,
    ))

    base["suggestion"] = _tonight_plan(rows, base["interventions"])

    prelim_any = any(
        o["tier"] == "preliminary" for iv in base["interventions"] for o in iv["outcomes"]
    )
    if powered:
        base["status"] = "analyzed"
        base["reliability"] = "high" if n >= 45 else ("medium" if n >= 21 else "low")
    elif prelim_any:
        base["status"] = "preliminary"
        base["remaining"] = max(0, _MIN_NIGHTS - n)
    else:
        base["status"] = "accumulating"
        base["remaining"] = max(0, _MIN_NIGHTS - n)
    return base


def _deconfound(rows: list[dict[str, Any]], label: dict[str, str]) -> dict[str, str] | None:
    """2 介入がほぼ常に同時 (着脱が一致しすぎ) なら「今夜は一方だけ」を提案。"""
    keys = [k for k, _ in INTERVENTIONS]
    best: tuple[int, str, str] | None = None  # (不一致夜数, keyA, keyB)
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a, b = keys[i], keys[j]
            both = [r for r in rows if r.get(a) is not None and r.get(b) is not None]
            if len(both) < _MIN_NIGHTS:
                continue
            discordant = sum(1 for r in both if r[a] != r[b])
            a_on = sum(1 for r in both if r[a] is True)
            b_on = sum(1 for r in both if r[b] is True)
            if discordant < _MIN_GROUP and a_on >= _MIN_GROUP and b_on >= _MIN_GROUP:
                if best is None or discordant < best[0]:
                    best = (discordant, a, b)
    if best is None:
        return None
    _, a, b = best
    return {
        "kind": "deconfound",
        "text": f"今夜は{label[a]}と{label[b]}のどちらか一方だけにする",
        "reason": (
            f"{label[a]}と{label[b]}をほぼ毎晩セットで使っているため、"
            "どちらが効いているか分離できません。片方だけの夜を作ると切り分けられます。"
        ),
    }


def _tonight_plan(
    rows: list[dict[str, Any]], interventions: list[dict[str, Any]]
) -> dict[str, str] | None:
    """「今夜何で寝るべきか」を 1 手だけ提案 (夜1から動く探索+活用)。

    優先度: 交絡崩し > explore-off (ほぼ毎晩ON・未確定を今夜外す) > exploit (実証済みを継続) >
    explore-on (未検証の介入を今夜試す)。データ収集を優先しつつ、勝者が出たら継続を促す。
    """
    label = {k: v for k, v in INTERVENTIONS}
    by_key = {iv["key"]: iv for iv in interventions}

    def cover(key: str) -> tuple[int, int]:
        return (
            sum(1 for r in rows if r.get(key) is True),
            sum(1 for r in rows if r.get(key) is False),
        )

    def undecided(key: str) -> bool:
        iv = by_key.get(key)
        return iv is None or iv.get("verdict") in ("insufficient", "no_effect")

    # 1. 交絡崩し
    dc = _deconfound(rows, label)
    if dc:
        return dc

    # 2. explore-off: ほぼ毎晩ON・未確定 → 今夜外して比較群を作る
    off = []
    for key in _EXPLORE_ORDER:
        n_did, n_didnt = cover(key)
        if n_did >= _MIN_GROUP and n_didnt < _MIN_GROUP and undecided(key):
            off.append((n_didnt, _EXPLORE_ORDER.index(key), key))
    if off:
        off.sort()
        key = off[0][2]
        _, n_didnt = cover(key)
        return {
            "kind": "explore",
            "text": f"今夜は{label[key]}を外して寝てみる",
            "reason": (
                f"{label[key]}を外した夜が{n_didnt}夜しかなく、効果を判定できません。"
                "着けない夜を作ると比較できます。"
            ),
        }

    # 3. exploit: 実証済み (improves) の勝者を継続
    winners = [iv for iv in interventions if iv.get("verdict") == "improves"]
    if winners:
        iv = winners[0]
        pr = iv.get("primary") or {}
        det = f"（{pr['outcome_label']} +{abs(pr['diff'])}）" if pr else ""
        return {
            "kind": "exploit",
            "text": f"今夜も{iv['label']}をつける",
            "reason": f"あなたのデータで{iv['label']}は睡眠の質を上げると確認済み{det}。続けましょう。",
        }

    # 4. explore-on: 未検証の介入を今夜試す (夜1から)
    on = []
    for key in _EXPLORE_ORDER:
        n_did, _n_didnt = cover(key)
        if n_did < _MIN_GROUP and undecided(key):
            on.append((n_did, _EXPLORE_ORDER.index(key), key))
    if on:
        on.sort()
        key = on[0][2]
        n_did, _ = cover(key)
        if n_did == 0:
            reason = f"{label[key]}を試した夜がまだありません。まず数夜つけると効果を測れます。"
        else:
            reason = (
                f"{label[key]}を着けた夜が{n_did}夜しかなく、効果を判定できません。"
                "着ける夜を増やすと比較できます。"
            )
        return {"kind": "explore", "text": f"今夜は{label[key]}をつけて寝てみる", "reason": reason}

    return None


def analyze(target: date_type | None = None) -> dict[str, Any]:
    target = target or app_today()
    return _analyze_rows(_collect(target))
