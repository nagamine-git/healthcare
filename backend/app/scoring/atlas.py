"""メトリクス・アトラス: 散らばった指標を 総合点→ドメイン→指標 の構造ツリーに集約。

各リーフは 現状(current)/ 世の中(population: 中央値|percentile|基準範囲)/ 目標(target) を持つ。
既存のスコア・最新サンプル・母集団基準・目標設定を読み出して組み立てる薄い集約層。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.health import (
    BodyCompositionSample,
    DailyScore,
    FitnessTestResult,
    HealthCheckup,
    WeightSample,
)
from app.scoring import population_norms as norms
from app.scoring.fitness_test import FITNESS_TESTS, fitness_percentile
from app.scoring.profile import resolve_profile


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
) -> dict[str, Any]:
    return {
        "key": key, "label": label, "unit": unit, "direction": direction,
        "current": _r(current), "population": population, "target": _r(target),
        "children": [],
    }


def _median(metric: str, age: int | None, sex: str | None) -> dict | None:
    pair = norms.norm_for(metric, age, sex)
    return {"median": _r(pair[0])} if pair else None


def _condition_branch(score: DailyScore | None) -> dict[str, Any]:
    subs = [
        ("sleep", "睡眠", score.sleep_sub if score else None),
        ("hrv", "自律神経 (HRV)", score.hrv_sub if score else None),
        ("energy", "エネルギー", score.bb_sub if score else None),
        ("load", "運動負荷 (ACWR)", score.load_sub if score else None),
    ]
    children = [
        _leaf(k, label, unit="", current=v, target=100.0, direction="up")
        for k, label, v in subs
    ]
    return {
        "key": "condition", "label": "コンディション (日次)", "unit": "",
        "direction": "up", "current": _r(score.total if score else None),
        "population": None, "target": 100.0, "children": children,
    }


def _body_branch(session: Session, prof) -> dict[str, Any]:
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

    children = [
        _leaf("weight", "体重", unit="kg", current=weight, target=s.target_weight_kg, direction="band"),
        _leaf("body_fat", "体脂肪率", unit="%", current=bf,
              population=_median("body_fat", age, sex), target=s.target_body_fat_pct, direction="band"),
        _leaf("ffmi", "FFMI (筋肉質さ)", unit="", current=ffmi,
              population=_median("ffmi", age, sex), direction="up"),
        _leaf("bmi", "BMI", unit="", current=bmi,
              population=_median("bmi", age, sex), direction="band"),
    ]
    if bc:
        children += [
            _leaf("skeletal_muscle", "骨格筋量", unit="kg", current=bc.skeletal_muscle_kg, direction="up"),
            _leaf("visceral_fat", "内臓脂肪レベル", unit="lv", current=bc.visceral_fat_level, direction="down"),
            _leaf("bmr", "基礎代謝", unit="kcal", current=bc.bmr_kcal, direction="none"),
        ]
    return {"key": "body", "label": "体型", "unit": "", "direction": "none",
            "current": None, "population": None, "target": None, "children": children}


def _fitness_branch(session: Session, prof) -> dict[str, Any]:
    age, sex = prof.age, prof.sex
    children: list[dict] = []
    for key, defn in FITNESS_TESTS.items():
        row = session.execute(
            select(FitnessTestResult)
            .where(FitnessTestResult.test_key == key)
            .order_by(FitnessTestResult.performed_on.desc())
            .limit(1)
        ).scalars().first()
        value = row.value if row else None
        pct = fitness_percentile(key, value, age, sex) if value is not None else None
        children.append(
            _leaf(
                key, defn.label, unit=defn.unit, current=value,
                population={"percentile": _r(pct)} if pct is not None else None,
                direction="up" if defn.higher_is_better else "down",
            )
        )
    return {"key": "fitness", "label": "体力測定", "unit": "", "direction": "up",
            "current": None, "population": None, "target": None, "children": children}


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
            _leaf(
                item["key"], item["label"], unit=item.get("unit", ""),
                current=(v or {}).get("value"),
                population={"range": [lo, hi]} if (lo is not None or hi is not None) else None,
                direction="band",
            )
        )
    return {"key": "checkup", "label": "健康診断", "unit": "", "direction": "band",
            "current": None, "population": None, "target": None, "children": children}


def build_atlas(session: Session) -> dict[str, Any]:
    """総合点を根に、各ドメイン→指標を 現状/世の中/目標 付きで組み立てる。"""
    prof = resolve_profile()
    score = session.execute(
        select(DailyScore).order_by(DailyScore.date.desc()).limit(1)
    ).scalars().first()
    return {
        "key": "total", "label": "総合点", "unit": "", "direction": "up",
        "current": _r(score.total if score else None), "population": None, "target": 100.0,
        "children": [
            _condition_branch(score),
            _body_branch(session, prof),
            _fitness_branch(session, prof),
            _checkup_branch(session),
        ],
    }
