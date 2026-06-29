"""メトリクス・アトラス: 散らばった指標を 総合点→ドメイン→指標 の構造ツリーに集約。

各リーフは 現状(current)/ 世の中(population)/ 目標(target) に加え、可視化用の
series(時系列)と score(0-100 正規化、レーダー用)を持つ。既存のスコア・最新サンプル・
母集団基準・目標設定を読み出して組み立てる薄い集約層。
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.health import (
    BodyCompositionSample,
    CaffeineIntake,
    DailyScore,
    DailySummary,
    FitnessTestResult,
    HealthCheckup,
    LearningSectionProgress,
    WeightSample,
)
from app.scoring import population_norms as norms
from app.scoring.caffeine import MEDICATION_CAFFEINE_SOURCES
from app.scoring.fitness_test import FITNESS_TESTS, fitness_percentile
from app.scoring.profile import resolve_profile
from app.scoring.timewindow import app_today, jst_day_bounds, jst_window_start


def _r(v: float | None, n: int = 1) -> float | None:
    return None if v is None else round(float(v), n)


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
) -> dict[str, Any]:
    return {
        "key": key, "label": label, "unit": unit, "direction": direction,
        "current": _r(current), "population": population, "target": _r(target),
        "score": _r(score), "series": series or [],
        "children": [],
    }


def _branch(key: str, label: str, children: list[dict], *, direction: str = "none",
            current: float | None = None, target: float | None = None) -> dict[str, Any]:
    return {
        "key": key, "label": label, "unit": "", "direction": direction,
        "current": _r(current), "population": None, "target": _r(target),
        "score": None, "series": [], "children": children,
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
    return _branch("condition", "コンディション (日次)", children, direction="up",
                   current=score.total if score else None, target=100.0)


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
              population=_median("ffmi", age, sex), direction="up"),
        _leaf("bmi", "BMI", unit="", current=bmi, population=_median("bmi", age, sex), direction="band"),
    ]
    if bc:
        children += [
            _leaf("skeletal_muscle", "骨格筋量", unit="kg", current=bc.skeletal_muscle_kg,
                  direction="up", series=sm_series),
            _leaf("visceral_fat", "内臓脂肪レベル", unit="lv", current=bc.visceral_fat_level, direction="down"),
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
        pct = fitness_percentile(key, value, age, sex) if value is not None else None
        hist = session.execute(
            select(FitnessTestResult.performed_on, FitnessTestResult.value)
            .where(FitnessTestResult.test_key == key).order_by(FitnessTestResult.performed_on)
        ).all()
        series = [{"date": d.isoformat(), "value": _r(v)} for d, v in hist if v is not None]
        children.append(
            _leaf(key, defn.label, unit=defn.unit, current=value,
                  population={"percentile": _r(pct)} if pct is not None else None,
                  direction="up" if defn.higher_is_better else "down",
                  score=_r(pct), series=series)
        )
    return _branch("fitness", "体力測定", children, direction="up")


def _headache_branch(session: Session, target: date_type) -> dict[str, Any]:
    s = get_settings()
    lo = jst_window_start(30, target)
    _, hi = jst_day_bounds(target)
    rows = session.execute(
        select(CaffeineIntake.ts).where(
            CaffeineIntake.source.in_(tuple(MEDICATION_CAFFEINE_SOURCES)),
            CaffeineIntake.ts >= lo, CaffeineIntake.ts < hi,
        )
    ).scalars().all()
    med_days = len({(t + timedelta(hours=9)).date() for t in rows})  # JST 暦日
    moh = float(s.med_max_doses_per_day) if hasattr(s, "med_max_doses_per_day") else None
    # MOH(薬物乱用頭痛)の警戒は月10日。target=10未満、基準範囲の上限として 10 を出す。
    leaf = _leaf(
        "med_days", "鎮痛薬 使用日数 (30日)", unit="日", current=float(med_days),
        population={"range": [None, 10]}, target=9.0, direction="down",
    )
    _ = moh
    return _branch("headache", "頭痛 (鎮痛薬)", [leaf], direction="down")


def _learning_activity_branch(session: Session, target: date_type) -> dict[str, Any]:
    sections_read = session.execute(
        select(func.count()).select_from(LearningSectionProgress)
        .where(LearningSectionProgress.read_at.is_not(None))
    ).scalar_one()
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
        _leaf("learning_sections", "学習: 読了した節", unit="節", current=float(sections_read), direction="up"),
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
        children.append(
            _leaf(item["key"], item["label"], unit=item.get("unit", ""),
                  current=(v or {}).get("value"),
                  population={"range": [lo, hi]} if (lo is not None or hi is not None) else None,
                  direction="band")
        )
    return _branch("checkup", "健康診断", children, direction="band")


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
            _condition_branch(session, target, score),
            _body_branch(session, target, prof),
            _fitness_branch(session, prof),
            _headache_branch(session, target),
            _learning_activity_branch(session, target),
            _checkup_branch(session),
        ],
        direction="up",
        current=score.total if score else None,
        target=100.0,
    ) | {"series": _ds_series(session, target, DailyScore.total)}
