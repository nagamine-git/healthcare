"""メトリクス・アトラス: 散らばった指標を 総合点→ドメイン→指標 の構造ツリーに集約。

各リーフは 現状(current)/ 世の中(population)/ 目標(target) に加え、可視化用の
series(時系列)と score(0-100 正規化、レーダー用)を持つ。既存のスコア・最新サンプル・
母集団基準・目標設定を読み出して組み立てる薄い集約層。
"""

from __future__ import annotations

import math
from datetime import date as date_type
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.health import (
    BodyCompositionSample,
    CaffeineIntake,
    DailyScore,
    DailySummary,
    FitnessTestResult,
    HealthCheckup,
    WeightSample,
)
from app.scoring import population_norms as norms
from app.scoring.caffeine import MEDICATION_CAFFEINE_SOURCES
from app.scoring.fitness_test import (
    FITNESS_TESTS,
    fitness_norm,
    fitness_percentile,
    srt_percentile,
)
from app.scoring.learning import TOTAL_SECTIONS
from app.scoring.profile import resolve_profile
from app.scoring.timewindow import app_today, jst_day_bounds, jst_window_start


def _r(v: float | None, n: int = 1) -> float | None:
    return None if v is None else round(float(v), n)


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _score_from(
    current: float | None, median: float | None, target: float | None, direction: str
) -> float | None:
    """指標を 0-100 の「良さ」に正規化(レーダー/ドメイン総合点用)。

    目標があれば目標基準、無ければ中央値基準(中央値=50点)。band は目標/中央値からの距離。
    あくまで俯瞰用の近似。
    """
    if current is None or direction == "none":
        return None
    ref = target if target is not None else median
    if ref is None or ref == 0:
        return None
    if direction == "up":
        scale = 100.0 if target is not None else 50.0
        return round(_clamp(current / ref * scale), 1)
    if direction == "down":
        if current <= 0:
            return 100.0
        scale = 100.0 if target is not None else 50.0
        return round(_clamp(ref / current * scale), 1)
    # band: 目標/中央値からの相対距離
    return round(_clamp(100.0 - abs(current - ref) / ref * 100.0), 1)


def _leaf(
    key: str,
    label: str,
    *,
    unit: str = "",
    current: float | None = None,
    population: dict | None = None,
    target: float | None = None,
    direction: str = "none",
    score: float | None = None,
    series: list[dict] | None = None,
    median: float | None = None,
) -> dict[str, Any]:
    # median はスコア計算用の中央値(表示は population)。明示が無ければ population から。
    median_v = median if median is not None else (population.get("median") if population else None)
    explicit_target = target  # 中央値フォールバック前の実目標
    # スコアは「実目標(明示/推定)」基準で算出(目標が無い時は中央値=50点扱い)。
    if score is None:
        score = _score_from(current, median_v, explicit_target, direction)
    # 中央値を同じ正規化に載せたスコア(レーダーの「中央値」系列用)。
    score_pop = (
        _score_from(median_v, median_v, explicit_target, direction)
        if median_v is not None else None
    )
    # 表示目標: 推定できなければ中央値を目標とする(ユーザー指定のフォールバック)。
    if target is None and median_v is not None:
        target = median_v
    return {
        "key": key, "label": label, "unit": unit, "direction": direction,
        "current": _r(current), "population": population, "target": _r(target),
        "score": _r(score), "score_pop": _r(score_pop), "series": series or [],
        "children": [],
    }


def _branch(key: str, label: str, children: list[dict], *, direction: str = "none",
            current: float | None = None, target: float | None = None,
            score: float | None = None, series: list[dict] | None = None) -> dict[str, Any]:
    # ドメイン総合点: 明示が無ければ子リーフ score の平均(レーダー軸/閉時表示に使う)。
    if score is None:
        vals = [c["score"] for c in children if c.get("score") is not None]
        score = round(sum(vals) / len(vals), 1) if vals else None
    pops = [c["score_pop"] for c in children if c.get("score_pop") is not None]
    score_pop = round(sum(pops) / len(pops), 1) if pops else None
    return {
        "key": key, "label": label, "unit": "", "direction": direction,
        "current": _r(current), "population": None, "target": _r(target),
        "score": _r(score), "score_pop": score_pop, "series": series or [], "children": children,
    }


def _median(metric: str, age: int | None, sex: str | None) -> dict | None:
    pair = norms.norm_for(metric, age, sex)
    return {"median": _r(pair[0])} if pair else None


def _ds_series(session: Session, target: date_type, field, days: int = 30) -> list[dict]:
    start = target - timedelta(days=days)
    rows = session.execute(
        select(DailyScore.date, field)
        .where(DailyScore.date >= start, DailyScore.date <= target)
        .order_by(DailyScore.date)
    ).all()
    return [{"date": d.isoformat(), "value": _r(v)} for d, v in rows if v is not None]


def _condition_branch(session: Session, target: date_type, score: DailyScore | None) -> dict[str, Any]:
    subs = [
        ("sleep", "睡眠", score.sleep_sub if score else None, DailyScore.sleep_sub),
        ("hrv", "自律神経 (HRV)", score.hrv_sub if score else None, DailyScore.hrv_sub),
        ("energy", "エネルギー", score.bb_sub if score else None, DailyScore.bb_sub),
        ("load", "運動負荷 (ACWR)", score.load_sub if score else None, DailyScore.load_sub),
    ]
    children = [
        _leaf(k, label, current=v, target=100.0, direction="up", score=v,
              series=_ds_series(session, target, field))
        for k, label, v, field in subs
    ]
    total = score.total if score else None
    return _branch("condition", "コンディション (日次)", children, direction="up",
                   current=total, target=100.0, score=total,
                   series=_ds_series(session, target, DailyScore.total))


def _body_branch(session: Session, target: date_type, prof) -> dict[str, Any]:
    s = get_settings()
    w = session.execute(
        select(WeightSample).order_by(WeightSample.ts.desc()).limit(1)
    ).scalars().first()
    bc = session.execute(
        select(BodyCompositionSample).order_by(BodyCompositionSample.date.desc()).limit(1)
    ).scalars().first()
    age, sex = prof.age, prof.sex
    height_m = (prof.height_cm or 0) / 100.0
    weight = w.weight_kg if w else None
    bf = w.body_fat_pct if w else None
    bmi = weight / (height_m**2) if weight and height_m else None
    lean = weight * (1 - bf / 100) if (weight is not None and bf is not None) else None
    ffmi = lean / (height_m**2) if (lean is not None and height_m) else None

    wstart = jst_window_start(30, target)
    wrows = session.execute(
        select(WeightSample.ts, WeightSample.weight_kg, WeightSample.body_fat_pct)
        .where(WeightSample.ts >= wstart).order_by(WeightSample.ts)
    ).all()
    w_series = [{"date": t.date().isoformat(), "value": _r(kg)} for t, kg, _ in wrows if kg is not None]
    bf_series = [{"date": t.date().isoformat(), "value": _r(p)} for t, _, p in wrows if p is not None]

    bcrows = session.execute(
        select(BodyCompositionSample.date, BodyCompositionSample.skeletal_muscle_kg)
        .where(BodyCompositionSample.date >= target - timedelta(days=180))
        .order_by(BodyCompositionSample.date)
    ).all()
    sm_series = [{"date": d.isoformat(), "value": _r(v)} for d, v in bcrows if v is not None]

    children = [
        _leaf("weight", "体重", unit="kg", current=weight, target=s.target_weight_kg,
              direction="band", series=w_series),
        _leaf("body_fat", "体脂肪率", unit="%", current=bf, population=_median("body_fat", age, sex),
              target=s.target_body_fat_pct, direction="band", series=bf_series),
        _leaf("ffmi", "FFMI (筋肉質さ)", unit="", current=ffmi,
              population=_median("ffmi", age, sex),
              target=20.0 if sex == "male" else 16.0, direction="up"),  # 推定: 良好域
        _leaf("bmi", "BMI", unit="", current=bmi, population=_median("bmi", age, sex),
              target=22.0, direction="band"),  # 推定: 標準体重(BMI22)
    ]
    if bc:
        children += [
            _leaf("skeletal_muscle", "骨格筋量", unit="kg", current=bc.skeletal_muscle_kg,
                  direction="up", series=sm_series),
            _leaf("visceral_fat", "内臓脂肪レベル", unit="lv", current=bc.visceral_fat_level,
                  target=9.0, direction="down"),  # 推定: 標準上限(Tanita ≤9)
            _leaf("bmr", "基礎代謝", unit="kcal", current=bc.bmr_kcal, direction="none"),
        ]
    return _branch("body", "体型", children)


def _fitness_branch(session: Session, prof) -> dict[str, Any]:
    age, sex = prof.age, prof.sex
    children: list[dict] = []
    for key, defn in FITNESS_TESTS.items():
        row = session.execute(
            select(FitnessTestResult).where(FitnessTestResult.test_key == key)
            .order_by(FitnessTestResult.performed_on.desc()).limit(1)
        ).scalars().first()
        value = row.value if row else None
        # 「世の中」列はパーセンタイル(順位)を表示。SRT は専用換算。
        if value is None:
            pct = None
        elif key == "srt":
            pct = srt_percentile(value)
        else:
            pct = fitness_percentile(key, value, age, sex)
        # レーダー/スコアは「良好値(目標)への達成度」で他ドメインと尺度を揃える。
        # 目標(良好値)= 基準 mean + 0.5*sd ≒ 上位3割。SRT は満点近い 9 を良好とする。
        norm = None if key == "srt" else fitness_norm(key, age, sex)
        good = (norm[0] + 0.5 * norm[1]) if norm else (9.0 if key == "srt" else None)
        median_val = norm[0] if norm else None
        hist = session.execute(
            select(FitnessTestResult.performed_on, FitnessTestResult.value)
            .where(FitnessTestResult.test_key == key).order_by(FitnessTestResult.performed_on)
        ).all()
        series = [{"date": d.isoformat(), "value": _r(v)} for d, v in hist if v is not None]
        children.append(
            _leaf(key, defn.label, unit=defn.unit, current=value,
                  population={"percentile": _r(pct)} if pct is not None else None,
                  median=median_val, target=_r(good),
                  direction="up" if defn.higher_is_better else "down", series=series)
        )
    return _branch("fitness", "体力測定", children, direction="up")


def _headache_branch(session: Session, target: date_type) -> dict[str, Any]:
    lo = jst_window_start(30, target)
    _, hi = jst_day_bounds(target)
    rows = session.execute(
        select(CaffeineIntake.ts).where(
            CaffeineIntake.source.in_(tuple(MEDICATION_CAFFEINE_SOURCES)),
            CaffeineIntake.ts >= lo, CaffeineIntake.ts < hi,
        )
    ).scalars().all()
    med_days = len({(t + timedelta(hours=9)).date() for t in rows})  # JST 暦日
    # MOH(薬物乱用頭痛)警戒は月10-15日。基準上限=10、目標(理想)=月4日以下に。
    leaf = _leaf(
        "med_days", "鎮痛薬 使用日数 (30日)", unit="日", current=float(med_days),
        population={"range": [None, 10]}, target=4.0, direction="down",
    )
    return _branch("headache", "頭痛 (鎮痛薬)", [leaf], direction="down")


def _learning_leaf(target: date_type) -> dict[str, Any]:
    """学習: 全カリキュラム比ではなく「今日のノルマ達成度」で評価(過度に厳しくしない)。

    目標 = 今日終わってるべきノルマ(最低ライン = done + needed_today_min)、
    中央値相当 = 楽観ノルマ(stretch = done + needed_today_safe)。計画が無ければ全体進捗。
    """
    from app.scoring.learning import projection

    try:
        proj = projection(target)
    except Exception:
        proj = None
    if proj and proj.get("needed_today_min") is not None:
        done = float(proj["done_units"])
        norm = done + float(proj["needed_today_min"])  # 今日のノルマ(目標)
        safe = float(proj["needed_today_safe"] or proj["needed_today_min"])
        stretch = done + safe  # 楽観ノルマ(中央値相当)
        return _leaf("learning", "学習: 今日のノルマ達成", unit="", current=done,
                     median=stretch, target=norm, direction="up")
    done_total = float(proj["done_units"]) if proj else 0.0
    total = float(proj["total_units"]) if proj else float(TOTAL_SECTIONS)
    return _leaf("learning", "学習: 全体進捗", unit="", current=done_total,
                 target=total, direction="up")


def _learning_activity_branch(session: Session, target: date_type) -> dict[str, Any]:
    summary = session.execute(
        select(DailySummary).order_by(DailySummary.date.desc()).limit(1)
    ).scalars().first()
    steps = summary.steps if summary else None
    sstart = target - timedelta(days=30)
    srows = session.execute(
        select(DailySummary.date, DailySummary.steps)
        .where(DailySummary.date >= sstart, DailySummary.date <= target).order_by(DailySummary.date)
    ).all()
    step_series = [{"date": d.isoformat(), "value": v} for d, v in srows if v is not None]
    return _branch("life", "学習・活動", [
        _learning_leaf(target),
        _leaf("steps", "歩数 (直近)", unit="歩", current=steps,
              target=float(get_settings().garden_steps_goal), direction="up", series=step_series),
    ], direction="up")


def _checkup_branch(session: Session) -> dict[str, Any]:
    s = get_settings()
    row = session.execute(
        select(HealthCheckup).order_by(HealthCheckup.date.desc(), HealthCheckup.id.desc()).limit(1)
    ).scalars().first()
    by_key = {v.get("key"): v for v in (row.values or [])} if row else {}
    children: list[dict] = []
    for item in s.checkup_items:
        v = by_key.get(item["key"])
        lo, hi = item.get("lo"), item.get("hi")
        cur = (v or {}).get("value")
        # 推定目標: 両側は基準範囲の中央、片側はその境界(範囲内に収める)。
        if lo is not None and hi is not None:
            tgt = (lo + hi) / 2
        else:
            tgt = hi if hi is not None else lo
        # スコア: 範囲内なら100、外なら境界からの逸脱で減点。
        if cur is None:
            sc = None
        elif (lo is None or cur >= lo) and (hi is None or cur <= hi):
            sc = 100.0
        else:
            ref = hi if (hi is not None and cur > hi) else lo
            sc = round(_clamp(100.0 - abs(cur - ref) / ref * 100.0), 1) if ref else 50.0
        children.append(
            _leaf(item["key"], item["label"], unit=item.get("unit", ""), current=cur,
                  population={"range": [lo, hi]} if (lo is not None or hi is not None) else None,
                  target=tgt, direction="band", score=sc)
        )
    return _branch("checkup", "健康診断", children, direction="band")


def _economy_branch(session: Session) -> dict[str, Any]:
    """資産: 看板=√(総資産×純資産)(単位が円で読める幾何平均) + 純資産 + 貯蓄率。"""
    from app.scoring.finance import compute_advisor, compute_cashflow, compute_rebalance

    reb = compute_rebalance(session)
    cf = compute_cashflow(session, reb.get("total") or 0.0)
    adv = compute_advisor(session, reb, cf)
    gross = adv.get("gross") or 0.0
    net = adv.get("net") or 0.0
    wealth_index = math.sqrt(gross * net) if gross > 0 and net > 0 else None
    inc = cf.get("avg_monthly_income")
    net_m = cf.get("avg_monthly_net")
    savings_rate = (net_m / inc * 100) if (inc and inc > 0 and net_m is not None) else None
    children = [
        _leaf("wealth_index", "√(総資産×純資産)", current=wealth_index, unit="円", direction="up"),
        _leaf("net_worth", "純資産", current=net, unit="円", direction="up"),
        _leaf("savings_rate", "貯蓄率", current=savings_rate, unit="%", direction="up", target=15.0),
    ]
    return _branch("economy", "資産", children, direction="up")


def _identity_branch(session: Session) -> dict[str, Any]:
    """羅針盤: マインドセット層・価値観層(現状 vs 理想=目標)。理想プロファイル由来。"""
    from app.scoring.identity.store import build_gap_report

    rep = build_gap_report(session)
    dims = rep.get("dimensions", [])

    def sub(layer: str, key: str, label: str) -> dict[str, Any] | None:
        leaves = [
            _leaf(str(d.get("id")), str(d.get("name") or d.get("id")),
                  current=d.get("current"), target=d.get("target"), direction="up")
            for d in dims
            if d.get("layer") == layer and d.get("current") is not None
        ]
        return _branch(key, label, leaves, direction="up") if leaves else None

    children = [
        b for b in (sub("mindset", "mindset", "マインドセット層"),
                    sub("values", "values", "価値観層")) if b
    ]
    if not children:
        return _branch("identity", "羅針盤 (理想)", [])
    return _branch("identity", "羅針盤 (理想)", children, direction="up")


def build_atlas(session: Session) -> dict[str, Any]:
    """総合点を根に、各ドメイン→指標を 現状/世の中/目標 + series/score 付きで組み立てる。"""
    prof = resolve_profile()
    target = app_today()
    score = session.execute(
        select(DailyScore).order_by(DailyScore.date.desc()).limit(1)
    ).scalars().first()
    return _branch(
        "total", "総合点",
        [
            _economy_branch(session),
            _condition_branch(session, target, score),
            _body_branch(session, target, prof),
            _fitness_branch(session, prof),
            _headache_branch(session, target),
            _learning_activity_branch(session, target),
            _checkup_branch(session),
            _identity_branch(session),
        ],
        direction="up",
        current=score.total if score else None,
        target=100.0,
    ) | {"series": _ds_series(session, target, DailyScore.total)}
