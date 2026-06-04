# トレンド再設計(理想達成度)実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`).

**Goal:** 各健康指標を「理想達成度(連続0-100)」で評価し、生値グラフ+理想ゾーン+回帰線+達成度方向で可視化する。

**Architecture:** 達成度の純粋関数(`achievement.py`)、回帰・方向・集計(`trends.py`)、DB生値取得(`trend_sources.py`)に分離。`/api/trends` が組み立て、frontend の `TrendCard` が描画。`daily_score` 採点は不変。

**Tech Stack:** Python/FastAPI/SQLAlchemy/pytest、React/TS/recharts。

---

## Task 1: 達成度の純粋関数 `achievement.py`

**Files:** Create `backend/app/scoring/achievement.py`, Test `backend/tests/test_achievement.py`

- [ ] **Step 1: 失敗するテスト**

`backend/tests/test_achievement.py`:
```python
from __future__ import annotations

from app.scoring import achievement as ach


def test_band_inside_is_100():
    assert ach.band_achievement(480, 420, 540, 90) == 100.0
    assert ach.band_achievement(420, 420, 540, 90) == 100.0


def test_band_half_at_softness():
    # 帯端から softness 離れると ~50
    v = ach.band_achievement(540 + 90, 420, 540, 90)
    assert 49.0 <= v <= 51.0


def test_band_symmetric():
    lo, hi, s = 420, 540, 90
    assert abs(ach.band_achievement(lo - 45, lo, hi, s) - ach.band_achievement(hi + 45, lo, hi, s)) < 1e-9


def test_upper_bounds():
    assert ach.upper_achievement(10, 20, 80) == 0.0
    assert ach.upper_achievement(80, 20, 80) == 100.0
    assert ach.upper_achievement(50, 20, 80) == 50.0


def test_sleep_quality_weighted():
    # 時間は理想(480→time 100)、質40 → 0.4*100 + 0.6*40 = 64
    a = ach.sleep_achievement(total_min=480, garmin_sleep_score=40,
                              deep_min=None, rem_min=None, light_min=None, awake_min=None)
    assert abs(a - 64.0) < 1e-6


def test_sleep_quality_missing_uses_time_only():
    a = ach.sleep_achievement(total_min=480, garmin_sleep_score=None,
                              deep_min=None, rem_min=None, light_min=None, awake_min=None)
    assert a == 100.0  # 質が無いので時間のみ(480 は帯中心)


def test_sleep_too_long_decays():
    a = ach.sleep_achievement(total_min=660, garmin_sleep_score=None,
                              deep_min=None, rem_min=None, light_min=None, awake_min=None)
    assert a < 60.0  # 11h は理想帯から大きく外れる


def test_hrv_achievement_clamps():
    from app.scoring.baselines import Baseline
    bl = Baseline(mean=60.0, std=10.0, n=28)
    assert ach.hrv_achievement(60.0, bl) == 50.0   # z=0
    assert ach.hrv_achievement(120.0, bl) == 100.0  # z>=2
    assert ach.hrv_achievement(0.0, bl) == 0.0      # z<=-2
```

- [ ] **Step 2: 失敗確認** `Run: docker一括(末尾参照) / 単体: pytest tests/test_achievement.py` Expected: ImportError

- [ ] **Step 3: 実装**

`backend/app/scoring/achievement.py`:
```python
"""理想値/理想帯からの達成度 (連続 0-100) を計算する DB 非依存の純粋関数群。

採点ロジック (daily_score) とは独立。トレンド表示専用。
全ての達成度は「高いほど理想に近い」に統一される。
"""

from __future__ import annotations

from app.scoring.baselines import Baseline

# 睡眠の合成重み (質側に重み)。後で調整可能。
SLEEP_TIME_WEIGHT = 0.4
SLEEP_QUALITY_WEIGHT = 0.6

# 睡眠時間の理想帯 (分) と減衰幅。
SLEEP_BAND_LO = 420
SLEEP_BAND_HI = 540
SLEEP_BAND_SOFTNESS = 90

# エネルギー (Body Battery) の片側パラメータ。
ENERGY_FLOOR = 20.0
ENERGY_GOOD = 80.0

# 運動負荷 (ACWR) の理想帯。
LOAD_BAND_LO = 0.8
LOAD_BAND_HI = 1.3
LOAD_BAND_SOFTNESS = 0.3


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def band_achievement(value: float, lo: float, hi: float, softness: float) -> float:
    """理想帯 [lo, hi] 内で 100、外側はローレンツ関数で滑らかに減衰。"""
    if lo <= value <= hi:
        return 100.0
    d = min(abs(value - lo), abs(value - hi))
    s = softness if softness > 1e-9 else 1e-9
    return 100.0 / (1.0 + (d / s) ** 2)


def upper_achievement(value: float, floor: float, good: float) -> float:
    """floor で 0、good 以上で 100、間は線形 (高いほど良い指標)。"""
    if good <= floor:
        return 100.0 if value >= good else 0.0
    return _clamp((value - floor) / (good - floor) * 100.0)


def _quality_achievement(
    garmin_sleep_score: float | None,
    deep_min: int | None,
    rem_min: int | None,
    light_min: int | None,
    awake_min: int | None,
) -> float | None:
    """睡眠の質達成度。Garmin スコア優先、無ければ効率 + deep/rem 比。"""
    if garmin_sleep_score is not None:
        return _clamp(float(garmin_sleep_score))
    if None in (deep_min, rem_min, light_min, awake_min):
        return None
    in_bed = deep_min + rem_min + light_min + awake_min
    if in_bed <= 0:
        return None
    efficiency = (in_bed - awake_min) / in_bed * 100
    ratio = (deep_min + rem_min) / in_bed
    ratio_score = _clamp(50 + (ratio - 0.20) * 250)
    return _clamp((efficiency + ratio_score) / 2)


def sleep_achievement(
    *,
    total_min: int | None,
    garmin_sleep_score: float | None,
    deep_min: int | None,
    rem_min: int | None,
    light_min: int | None,
    awake_min: int | None,
) -> float | None:
    """睡眠の合成達成度 = 0.4*時間 + 0.6*質 (質が無い日は時間のみ)。"""
    if total_min is None or total_min <= 0:
        return None
    time_ach = band_achievement(float(total_min), SLEEP_BAND_LO, SLEEP_BAND_HI, SLEEP_BAND_SOFTNESS)
    quality_ach = _quality_achievement(garmin_sleep_score, deep_min, rem_min, light_min, awake_min)
    if quality_ach is None:
        return time_ach
    return _clamp(SLEEP_TIME_WEIGHT * time_ach + SLEEP_QUALITY_WEIGHT * quality_ach)


def hrv_achievement(value: float | None, baseline: Baseline | None) -> float | None:
    if value is None or baseline is None:
        return None
    z = (float(value) - baseline.mean) / baseline.std
    z = max(-2.0, min(2.0, z))
    return _clamp(50.0 + 25.0 * z)


def energy_achievement(morning_value: float | None) -> float | None:
    if morning_value is None:
        return None
    return upper_achievement(float(morning_value), ENERGY_FLOOR, ENERGY_GOOD)


def load_achievement(acwr: float | None) -> float | None:
    if acwr is None:
        return None
    return band_achievement(float(acwr), LOAD_BAND_LO, LOAD_BAND_HI, LOAD_BAND_SOFTNESS)


def weight_achievement(value: float | None, target_kg: float) -> float | None:
    if value is None or target_kg <= 0:
        return None
    return band_achievement(float(value), target_kg - 1.0, target_kg + 1.0, 1.5)


def body_fat_achievement(value: float | None, target_pct: float, tol: float) -> float | None:
    if value is None or target_pct <= 0:
        return None
    return band_achievement(float(value), target_pct - tol, target_pct + tol, max(tol * 2, 0.5))
```

- [ ] **Step 4: テスト通過確認**

---

## Task 2: 回帰と達成度系列ヘルパ `trends.py` 改修

**Files:** Modify `backend/app/scoring/trends.py`, Modify `backend/tests/test_trends.py`

初版の `compute_trend` / `weekly_average` / `daily_series` / `_direction` / `_linear_slope` / `_mean` / `_clean` は残す
(達成度系列に流用)。`series_by_column` / `build_metrics` / `SCORE_COLUMNS` / `TREND_METRICS` は削除(新APIで使わない)。

- [ ] **Step 1: 失敗するテストを test_trends.py に追加**
```python
def test_linear_regression_endpoints():
    from app.scoring import trends
    s = [(date(2026, 5, 1) + timedelta(days=i), float(10 + 2 * i)) for i in range(5)]
    reg = trends.linear_regression_endpoints(s)
    assert reg["start"]["value"] == 10.0
    assert reg["end"]["value"] == 18.0
    assert reg["start"]["date"] == "2026-05-01"
    assert reg["end"]["date"] == "2026-05-05"


def test_linear_regression_too_few_points():
    from app.scoring import trends
    assert trends.linear_regression_endpoints([(date(2026, 5, 1), 5.0)]) is None
```

`test_series_by_column_and_build_metrics` を削除(対象関数を廃止するため)。

- [ ] **Step 2: 失敗確認**

- [ ] **Step 3: `trends.py` に追加し、不要関数を削除**

`series_by_column`/`build_metrics`/`SCORE_COLUMNS`/`TREND_METRICS` を削除。末尾に追加:
```python
def linear_regression_endpoints(
    series: list[tuple[date, float | None]],
) -> dict[str, Any] | None:
    """生値系列の線形回帰の両端2点を返す (グラフの点線用)。点が2未満なら None。"""
    pts = _clean(series)
    if len(pts) < 2:
        return None
    values = [v for _, v in pts]
    slope = _linear_slope(values)
    if slope is None:
        return None
    n = len(values)
    mean_y = sum(values) / n
    intercept = mean_y - slope * (n - 1) / 2  # x=0..n-1
    return {
        "start": {"date": pts[0][0].isoformat(), "value": round(intercept, 2)},
        "end": {"date": pts[-1][0].isoformat(), "value": round(intercept + slope * (n - 1), 2)},
    }
```

- [ ] **Step 4: テスト通過確認**(既存 compute_trend 系テストは維持)

---

## Task 3: 生値取得 `trend_sources.py`

**Files:** Create `backend/app/scoring/trend_sources.py`, Test `backend/tests/test_trend_sources.py`

- [ ] **Step 1: 失敗するテスト**

`backend/tests/test_trend_sources.py`:
```python
from __future__ import annotations

from datetime import date, datetime, timedelta

from app.db import session_scope
from app.models import BodyBatteryDaily, HrvDaily, SleepSession, WeightSample


def test_raw_series_collects_per_metric(db_engine):
    from app.scoring import trend_sources as ts

    today = date(2026, 5, 20)
    with session_scope() as session:
        for i in range(5):
            d = today - timedelta(days=i)
            session.add(SleepSession(date=d, source="garmin", total_min=420 + i * 10, sleep_score=80))
            session.add(HrvDaily(date=d, last_night_avg=60 + i, weekly_avg=60, status="BALANCED"))
            session.add(BodyBatteryDaily(date=d, max_value=90, min_value=20, end_of_day=40, morning_value=70 + i))
            session.add(WeightSample(ts=datetime.combine(d, datetime.min.time()),
                                     weight_kg=70.0 + i * 0.1, body_fat_pct=18.0, source="hae"))

    bundle = ts.collect_raw_series(today, days=28)
    assert len(bundle["sleep"]) == 5
    assert len(bundle["hrv"]) == 5
    assert len(bundle["energy"]) == 5
    assert len(bundle["weight"]) == 5
    assert len(bundle["body_fat"]) == 5
    # sleep は (date, total_min, score, deep, rem, light, awake) のタプル系列
    assert bundle["sleep"][0][1] in (420, 430, 440, 450, 460)
    assert bundle["hrv_baseline"] is not None
```

- [ ] **Step 2: 失敗確認**

- [ ] **Step 3: 実装**

`backend/app/scoring/trend_sources.py`:
```python
"""トレンド用に各指標の生値日次系列を DB から取得する。"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.db import session_scope
from app.models import BodyBatteryDaily, HrvDaily, SleepSession, WeightSample
from app.scoring.baselines import Baseline, build_baseline
from app.scoring.recompute import _training_load


def _weight_daily(rows: list[tuple[datetime, float | None]]) -> list[tuple[date_type, float]]:
    """WeightSample (ts, value) を JST 日付ごとの中央値に集約。"""
    from app.scoring.timewindow import JST
    from datetime import UTC

    by_day: dict[date_type, list[float]] = {}
    for ts, v in rows:
        if v is None or ts is None:
            continue
        d = ts.replace(tzinfo=UTC).astimezone(JST).date()
        by_day.setdefault(d, []).append(float(v))
    out: list[tuple[date_type, float]] = []
    for d in sorted(by_day):
        vals = sorted(by_day[d])
        n = len(vals)
        med = vals[n // 2] if n % 2 == 1 else (vals[n // 2 - 1] + vals[n // 2]) / 2
        out.append((d, med))
    return out


def daily_acwr_series(target: date_type, days: int) -> list[tuple[date_type, float]]:
    """各日付の ACWR (acute/chronic) を計算した系列。"""
    out: list[tuple[date_type, float]] = []
    with session_scope() as session:
        for i in range(days + 1):
            d = target - timedelta(days=i)
            acute, chronic = _training_load(session, d)
            if acute is not None and chronic and chronic > 0:
                out.append((d, acute / chronic))
    out.sort(key=lambda p: p[0])
    return out


def collect_raw_series(target: date_type, days: int = 28) -> dict[str, Any]:
    """全指標の生値日次系列 + HRV ベースラインを返す。"""
    start = target - timedelta(days=days)
    with session_scope() as session:
        sleep_rows = session.execute(
            select(
                SleepSession.date, SleepSession.total_min, SleepSession.sleep_score,
                SleepSession.deep_min, SleepSession.rem_min, SleepSession.light_min,
                SleepSession.awake_min,
            ).where(SleepSession.date >= start, SleepSession.date <= target)
            .order_by(SleepSession.date)
        ).all()
        hrv_rows = session.execute(
            select(HrvDaily.date, HrvDaily.last_night_avg)
            .where(HrvDaily.date >= start, HrvDaily.date <= target)
            .order_by(HrvDaily.date)
        ).all()
        energy_rows = session.execute(
            select(BodyBatteryDaily.date, BodyBatteryDaily.morning_value)
            .where(BodyBatteryDaily.date >= start, BodyBatteryDaily.date <= target)
            .order_by(BodyBatteryDaily.date)
        ).all()
        weight_rows = session.execute(
            select(WeightSample.ts, WeightSample.weight_kg)
            .where(WeightSample.ts >= datetime.combine(start, datetime.min.time()))
            .order_by(WeightSample.ts)
        ).all()
        fat_rows = session.execute(
            select(WeightSample.ts, WeightSample.body_fat_pct)
            .where(WeightSample.ts >= datetime.combine(start, datetime.min.time()))
            .order_by(WeightSample.ts)
        ).all()
        # HRV ベースライン (28日)
        hrv_vals = [r[1] for r in hrv_rows]

    return {
        "sleep": [tuple(r) for r in sleep_rows],
        "hrv": [(d, v) for d, v in hrv_rows if v is not None],
        "energy": [(d, v) for d, v in energy_rows if v is not None],
        "weight": _weight_daily(list(weight_rows)),
        "body_fat": _weight_daily(list(fat_rows)),
        "acwr": daily_acwr_series(target, days),
        "hrv_baseline": build_baseline(hrv_vals),
    }
```

- [ ] **Step 4: テスト通過確認**

---

## Task 4: `/api/trends` 改修

**Files:** Modify `backend/app/api/dashboard.py`, Modify `backend/tests/test_dashboard_api.py`

- [ ] **Step 1: 失敗するテスト(test_dashboard_api.py の旧 trends テスト2件を置換)**

`test_trends_endpoint_daily` / `test_trends_endpoint_weekly` を次に置き換え:
```python
def test_trends_endpoint_daily(app_client):
    from app.db import session_scope

    today = date.today()
    with session_scope() as session:
        for i in range(8):
            d = today - timedelta(days=7 - i)
            session.add(SleepSession(date=d, source="garmin", total_min=400 + i * 15, sleep_score=70 + i,
                                     deep_min=60, rem_min=90, light_min=240, awake_min=20))
            session.add(WeightSample(ts=datetime.combine(d, datetime.min.time()),
                                     weight_kg=72.0 - i * 0.1, body_fat_pct=18.0, source="hae"))

    resp = app_client.get("/api/trends", params={"granularity": "daily", "days": 28})
    assert resp.status_code == 200
    body = resp.json()
    assert body["granularity"] == "daily"
    assert set(body["metrics"].keys()) == {"sleep", "hrv", "energy", "load", "weight", "body_fat"}
    sleep = body["metrics"]["sleep"]
    assert sleep["ideal"]["type"] == "band"
    assert len(sleep["raw_series"]) == 8
    assert sleep["achievement"] is not None
    assert sleep["regression"] is not None
    assert sleep["direction"] in ("improving", "stable", "declining")


def test_trends_endpoint_weekly(app_client):
    from app.db import session_scope

    today = date.today()
    with session_scope() as session:
        for i in range(14):
            d = today - timedelta(days=13 - i)
            session.add(SleepSession(date=d, source="garmin", total_min=480, sleep_score=80))

    resp = app_client.get("/api/trends", params={"granularity": "weekly", "days": 28})
    assert resp.status_code == 200
    body = resp.json()
    assert body["granularity"] == "weekly"
    sleep = body["metrics"]["sleep"]
    assert sleep["regression"] is None
    assert len(sleep["raw_series"]) <= 3
```

`SleepSession` import を test ファイル先頭の models import に追加(既に DailyScore 等を import 済み。`SleepSession` は既にある)。

- [ ] **Step 2: 失敗確認**

- [ ] **Step 3: dashboard.py の trends エンドポイントを置換**

初版で追加した `@router.get("/api/trends")` 関数を次に置換:
```python
@router.get("/api/trends")
async def trends(
    granularity: str = Query(default="daily"),
    days: int = Query(default=28, ge=7, le=365),
) -> dict[str, Any]:
    from app.config import get_settings
    from app.scoring import achievement as ach
    from app.scoring import trend_sources, trends as tr

    s = get_settings()
    bundle = trend_sources.collect_raw_series(_today(), days=days)
    weekly = granularity == "weekly"

    def _ach_series(raw, fn):
        """raw: [(date, *args)] を [(date, achievement)] に。"""
        out = []
        for row in raw:
            d = row[0]
            a = fn(row)
            if a is not None:
                out.append((d, a))
        return out

    def _raw_pairs(raw):
        """(date, value) の生値ペア (raw の2要素目を値とみなす)。"""
        return [(row[0], row[1]) for row in raw]

    def _series_out(pairs):
        return tr.weekly_average(pairs) if weekly else tr.daily_series(pairs)

    def _metric(label, unit, ideal, raw_pairs, ach_series):
        trend = tr.compute_trend(ach_series, higher_is_better=True)
        return {
            "label": label,
            "unit": unit,
            "ideal": ideal,
            "raw_series": _series_out(raw_pairs),
            "current_raw": round(raw_pairs[-1][1], 2) if raw_pairs else None,
            "achievement": trend["current"],
            "achievement_prev_day_change": trend["prev_day_change"],
            "achievement_week_over_week": trend["week_over_week"],
            "direction": trend["direction"],
            "regression": None if weekly else tr.linear_regression_endpoints(raw_pairs),
        }

    # sleep: raw row = (date, total_min, score, deep, rem, light, awake)
    sleep_raw = bundle["sleep"]
    sleep_pairs = [(r[0], r[1]) for r in sleep_raw if r[1] is not None]
    sleep_ach = _ach_series(
        [r for r in sleep_raw if r[1] is not None],
        lambda r: ach.sleep_achievement(
            total_min=r[1], garmin_sleep_score=r[2],
            deep_min=r[3], rem_min=r[4], light_min=r[5], awake_min=r[6],
        ),
    )
    hrv_bl = bundle["hrv_baseline"]
    metrics = {
        "sleep": _metric("睡眠", "分", {"type": "band", "lo": ach.SLEEP_BAND_LO, "hi": ach.SLEEP_BAND_HI},
                         sleep_pairs, sleep_ach),
        "hrv": _metric(
            "自律神経 (HRV)", "ms",
            {"type": "upper", "good_line": round(hrv_bl.mean, 1) if hrv_bl else None},
            _raw_pairs(bundle["hrv"]),
            _ach_series(bundle["hrv"], lambda r: ach.hrv_achievement(r[1], hrv_bl)),
        ),
        "energy": _metric(
            "エネルギー", "",
            {"type": "upper", "good_line": ach.ENERGY_GOOD},
            _raw_pairs(bundle["energy"]),
            _ach_series(bundle["energy"], lambda r: ach.energy_achievement(r[1])),
        ),
        "load": _metric(
            "運動負荷 (ACWR)", "",
            {"type": "band", "lo": ach.LOAD_BAND_LO, "hi": ach.LOAD_BAND_HI},
            _raw_pairs(bundle["acwr"]),
            _ach_series(bundle["acwr"], lambda r: ach.load_achievement(r[1])),
        ),
        "weight": _metric(
            "体重", "kg",
            {"type": "band", "lo": round(s.target_weight_kg - 1.0, 1), "hi": round(s.target_weight_kg + 1.0, 1)},
            _raw_pairs(bundle["weight"]),
            _ach_series(bundle["weight"], lambda r: ach.weight_achievement(r[1], s.target_weight_kg)),
        ),
        "body_fat": _metric(
            "体脂肪率", "%",
            {"type": "band",
             "lo": round(s.target_body_fat_pct - s.body_fat_tolerance_pct, 1),
             "hi": round(s.target_body_fat_pct + s.body_fat_tolerance_pct, 1)},
            _raw_pairs(bundle["body_fat"]),
            _ach_series(bundle["body_fat"],
                        lambda r: ach.body_fat_achievement(r[1], s.target_body_fat_pct, s.body_fat_tolerance_pct)),
        ),
    }
    return {
        "granularity": granularity,
        "generated_at": _utc_iso(datetime.now(UTC).replace(tzinfo=None)),
        "metrics": metrics,
    }
```

- [ ] **Step 4: 既存 dashboard テスト全通過確認**

---

## Task 5: LLM `recent_trends` を達成度ベースに

**Files:** Modify `backend/app/llm/client.py`, Modify `backend/tests/test_llm.py`

- [ ] **Step 1: test_llm.py の `test_gather_recent_trends_builds_directions` を更新**
```python
def test_gather_recent_trends_builds_directions(db_engine):
    from datetime import date, datetime, timedelta

    from app.db import session_scope
    from app.llm.client import _gather_recent_trends
    from app.models import SleepSession

    today = date.today()
    with session_scope() as session:
        for i in range(8):
            d = today - timedelta(days=7 - i)
            session.add(SleepSession(date=d, source="garmin", total_min=400 + i * 15, sleep_score=70 + i,
                                     deep_min=60, rem_min=90, light_min=240, awake_min=20))

    trends = _gather_recent_trends(today)
    assert "sleep" in trends
    assert trends["sleep"]["direction"] in ("improving", "stable", "declining", None)
    assert "series" not in trends["sleep"]
```

- [ ] **Step 2: 失敗確認**

- [ ] **Step 3: `_gather_recent_trends` を書き換え**

`client.py` の `_gather_recent_trends` を次に置換(DailyScore 直読みをやめ、新APIと同じ計算を共有):
```python
def _gather_recent_trends(target: date_type, days: int = 28) -> dict[str, Any]:
    """直近の理想達成度トレンド (方向 + 前日比 + 前週比) を LLM 用にコンパクトに返す。"""
    from app.config import get_settings
    from app.scoring import achievement as ach
    from app.scoring import trend_sources, trends as tr

    s = get_settings()
    bundle = trend_sources.collect_raw_series(target, days=days)
    hrv_bl = bundle["hrv_baseline"]

    def _ach(raw, fn):
        return [(row[0], fn(row)) for row in raw if fn(row) is not None]

    series_map = {
        "sleep": _ach(
            [r for r in bundle["sleep"] if r[1] is not None],
            lambda r: ach.sleep_achievement(total_min=r[1], garmin_sleep_score=r[2],
                                            deep_min=r[3], rem_min=r[4], light_min=r[5], awake_min=r[6]),
        ),
        "hrv": _ach(bundle["hrv"], lambda r: ach.hrv_achievement(r[1], hrv_bl)),
        "energy": _ach(bundle["energy"], lambda r: ach.energy_achievement(r[1])),
        "load": _ach(bundle["acwr"], lambda r: ach.load_achievement(r[1])),
        "weight": _ach(bundle["weight"], lambda r: ach.weight_achievement(r[1], s.target_weight_kg)),
        "body_fat": _ach(bundle["body_fat"],
                         lambda r: ach.body_fat_achievement(r[1], s.target_body_fat_pct, s.body_fat_tolerance_pct)),
    }
    out: dict[str, Any] = {}
    for key, series in series_map.items():
        t = tr.compute_trend(series, higher_is_better=True)
        out[key] = {
            "direction": t["direction"],
            "achievement": t["current"],
            "prev_day_change": t["prev_day_change"],
            "week_over_week": t["week_over_week"],
        }
    return out
```

(プロンプト `prompts.py` の「# 最近のトレンド」セクションは初版のままで意味が通る。`direction` の語彙は不変。)

- [ ] **Step 4: backend 全テスト + ruff 通過確認**

---

## Task 6: frontend — 型・TrendBadge・TrendCard・Today

**Files:** Modify `frontend/src/lib/api.ts`, `frontend/src/components/TrendBadge.tsx`,
`frontend/src/components/Sparkline.tsx`, `frontend/src/pages/Trends.tsx`, `frontend/src/pages/Today.tsx`

- [ ] **Step 1: `api.ts` の型を新APIに合わせ置換**

初版で追加した `TrendDirection`/`TrendMetric`/`TrendMetricKey`/`TrendsResponse` を次に置換:
```typescript
export type TrendDirection = "improving" | "stable" | "declining";

export type IdealBand =
  | { type: "band"; lo: number; hi: number }
  | { type: "upper"; good_line: number | null };

export type TrendMetric = {
  label: string;
  unit: string;
  ideal: IdealBand;
  raw_series: TimeseriesPoint[];
  current_raw: number | null;
  achievement: number | null;
  achievement_prev_day_change: number | null;
  achievement_week_over_week: { delta: number; pct: number | null } | null;
  direction: TrendDirection | null;
  regression: { start: TimeseriesPoint; end: TimeseriesPoint } | null;
};

export type TrendMetricKey = "sleep" | "hrv" | "energy" | "load" | "weight" | "body_fat";

export type TrendsResponse = {
  granularity: "daily" | "weekly";
  generated_at: string | null;
  metrics: Record<TrendMetricKey, TrendMetric>;
};
```
(`TimeseriesPoint.value` は `number | null`。`regression` の値は number なので、利用時に `?? undefined` で扱う。)

- [ ] **Step 2: `TrendBadge.tsx` を達成度方向ベースに**

`prevDayChange` の意味を「達成度の前日変化」に変える。表示文言のみ調整:
```tsx
import type { TrendDirection } from "../lib/api";

type Props = {
  direction: TrendDirection | null;
  achievementChange?: number | null;
};

const ARROW: Record<TrendDirection, string> = { improving: "↗", stable: "→", declining: "↘" };
const LABEL: Record<TrendDirection, string> = { improving: "改善", stable: "横ばい", declining: "低下" };
const COLOR: Record<TrendDirection, string> = {
  improving: "text-emerald-400",
  stable: "text-slate-400",
  declining: "text-rose-400",
};

export function TrendBadge({ direction, achievementChange }: Props) {
  if (!direction) return <span className="text-xs text-slate-600">—</span>;
  const change =
    achievementChange != null && Math.abs(achievementChange) >= 0.1
      ? `${achievementChange > 0 ? "+" : ""}${achievementChange.toFixed(0)}`
      : null;
  return (
    <span className={`flex items-center gap-1 text-xs ${COLOR[direction]}`}>
      {change ? <span className="tabular-nums">{change}</span> : null}
      <span aria-label={LABEL[direction]}>{ARROW[direction]} {LABEL[direction]}</span>
    </span>
  );
}
```

- [ ] **Step 3: `Sparkline.tsx` の trend バッジ呼び出しを更新**

`TrendBadge` 呼び出しを `direction`/`achievementChange` に:
```tsx
        {trend ? (
          <TrendBadge direction={trend.direction} achievementChange={trend.achievement_prev_day_change} />
        ) : (
```
`import type { TimeseriesPoint, TrendMetric }` はそのまま有効。

- [ ] **Step 4: `Today.tsx` の Sparkline trend 受け渡しキーを更新**

`trends.data?.metrics.total` → 各指標キーに変更。総合スコアの Sparkline は HRV/エネルギー等が無いので、
4枚を `sleep` / `hrv` / `weight` に対応させ、体脂肪率カードを1枚追加。Sparkline セクションを次に置換:
```tsx
        <Sparkline label="睡眠時間 14日" data={sleepSeries.data?.data ?? []} color="#60a5fa"
          formatter={(v) => formatMinutes(v)} trend={trends.data?.metrics.sleep} />
        <Sparkline label="HRV 28日" data={hrvSeries.data?.data ?? []} color="#a78bfa"
          formatter={(v) => `${v.toFixed(0)} ms`} trend={trends.data?.metrics.hrv} />
        <Sparkline label="体重 28日" data={weightSeries.data?.data ?? []} color="#f472b6"
          formatter={(v) => `${v.toFixed(1)} kg`} trend={trends.data?.metrics.weight} />
        <Sparkline label="総合スコア 14日" data={scoreSeries.data?.data ?? []} color="#34d399" />
```
(総合スコア Sparkline は trend バッジ無しで日数表示に戻す。トレンドの主役は専用ページ。)

- [ ] **Step 5: `Trends.tsx`(TrendCard)を生値+理想ゾーン+回帰線に作り直す**

`frontend/src/pages/Trends.tsx` を全面置換(下記 Task 6 補足のコード)。`ReferenceArea`/`ReferenceLine`/`Line` を使う。

- [ ] **Step 6: `npm run build` で型チェック+ビルド通過確認**

---

## Task 6 補足: Trends.tsx 全文

```tsx
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Bar, BarChart, Line, LineChart, ReferenceArea, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { api } from "../lib/api";
import type { TrendDirection, TrendMetric, TrendMetricKey } from "../lib/api";

type Props = { onBack?: () => void };

const ORDER: TrendMetricKey[] = ["sleep", "hrv", "energy", "load", "weight", "body_fat"];

const DIR_LABEL: Record<TrendDirection, string> = {
  improving: "改善傾向", stable: "横ばい", declining: "低下傾向",
};
const DIR_COLOR: Record<TrendDirection, string> = {
  improving: "text-emerald-400", stable: "text-slate-400", declining: "text-rose-400",
};
const LINE = "#34d399";
const BAND = "#34d39922";

function TrendCard({ metric, granularity }: { metric: TrendMetric; granularity: "daily" | "weekly" }) {
  const data = metric.raw_series;
  const dir = metric.direction;
  const wow = metric.achievement_week_over_week;
  const reg =
    metric.regression && metric.regression.start.value != null && metric.regression.end.value != null
      ? [
          { date: metric.regression.start.date, reg: metric.regression.start.value },
          { date: metric.regression.end.date, reg: metric.regression.end.value },
        ]
      : null;
  // 回帰線を raw_series にマージ (両端のみ reg を持つ)
  const merged = data.map((p) => {
    if (!reg) return { ...p };
    if (p.date === reg[0].date) return { ...p, reg: reg[0].reg };
    if (p.date === reg[1].date) return { ...p, reg: reg[1].reg };
    return { ...p };
  });

  return (
    <div className="rounded-2xl bg-slate-900/70 p-4">
      <div className="mb-1 flex items-baseline justify-between">
        <span className="text-sm text-slate-200">{metric.label}</span>
        <span className="text-2xl font-light tabular-nums text-slate-100">
          {metric.current_raw != null ? `${metric.current_raw}${metric.unit}` : "--"}
        </span>
      </div>
      <div className="mb-2 flex items-center justify-between text-xs">
        <span className={dir ? DIR_COLOR[dir] : "text-slate-600"}>
          {dir ? DIR_LABEL[dir] : "データ不足"}
          {metric.achievement != null ? ` · 達成度 ${Math.round(metric.achievement)}` : ""}
        </span>
        <span className="text-slate-500">
          {wow ? `前週比 ${wow.delta > 0 ? "+" : ""}${wow.delta.toFixed(0)}` : ""}
        </span>
      </div>
      <div className="h-32">
        <ResponsiveContainer width="100%" height="100%">
          {granularity === "weekly" ? (
            <BarChart data={merged}>
              <XAxis dataKey="date" hide />
              <YAxis hide domain={["dataMin", "dataMax"]} />
              <Tooltip contentStyle={{ backgroundColor: "#1e293b", border: "1px solid #334155", fontSize: 12 }} />
              {metric.ideal.type === "band" ? (
                <ReferenceArea y1={metric.ideal.lo} y2={metric.ideal.hi} fill={BAND} stroke="none" />
              ) : metric.ideal.good_line != null ? (
                <ReferenceLine y={metric.ideal.good_line} stroke="#64748b" strokeDasharray="3 3" />
              ) : null}
              <Bar dataKey="value" fill={LINE} radius={[3, 3, 0, 0]} />
            </BarChart>
          ) : (
            <LineChart data={merged}>
              <XAxis dataKey="date" hide />
              <YAxis hide domain={["dataMin", "dataMax"]} />
              <Tooltip contentStyle={{ backgroundColor: "#1e293b", border: "1px solid #334155", fontSize: 12 }} />
              {metric.ideal.type === "band" ? (
                <ReferenceArea y1={metric.ideal.lo} y2={metric.ideal.hi} fill={BAND} stroke="none" />
              ) : metric.ideal.good_line != null ? (
                <ReferenceLine y={metric.ideal.good_line} stroke="#64748b" strokeDasharray="3 3" />
              ) : null}
              <Line type="monotone" dataKey="value" stroke={LINE} strokeWidth={2} dot={false} />
              {reg ? (
                <Line type="linear" dataKey="reg" stroke="#f59e0b" strokeWidth={1.5}
                      strokeDasharray="5 4" dot={false} connectNulls />
              ) : null}
            </LineChart>
          )}
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export function TrendsPage({ onBack }: Props) {
  const [granularity, setGranularity] = useState<"daily" | "weekly">("daily");
  const query = useQuery({
    queryKey: ["trends", granularity],
    queryFn: () => api.trends(granularity, granularity === "weekly" ? 84 : 28),
  });

  return (
    <main className="safe-area-x safe-area-bottom mx-auto max-w-5xl space-y-6 px-4 pb-8 sm:px-8">
      <header className="safe-area-top flex items-center justify-between pb-2 pt-3">
        <div className="flex items-center gap-3">
          <button onClick={onBack}
            className="rounded-lg bg-slate-800/70 px-2 py-1 text-xs text-slate-300 hover:bg-slate-700">← 戻る</button>
          <span className="text-sm text-slate-200">トレンド(理想への接近度)</span>
        </div>
        <div className="flex rounded-lg bg-slate-800/70 p-0.5 text-xs">
          <button onClick={() => setGranularity("daily")}
            className={`rounded-md px-3 py-1 ${granularity === "daily" ? "bg-slate-600 text-slate-100" : "text-slate-400"}`}>日次</button>
          <button onClick={() => setGranularity("weekly")}
            className={`rounded-md px-3 py-1 ${granularity === "weekly" ? "bg-slate-600 text-slate-100" : "text-slate-400"}`}>週次</button>
        </div>
      </header>
      {query.isLoading ? (
        <div className="text-slate-400">読み込み中...</div>
      ) : query.isError || !query.data ? (
        <div className="text-rose-400">取得に失敗しました</div>
      ) : (
        <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {ORDER.map((key) => (
            <TrendCard key={key} metric={query.data.metrics[key]} granularity={granularity} />
          ))}
        </section>
      )}
    </main>
  );
}
```

注: recharts の `ReferenceArea`/`ReferenceLine` の `y` 値はグラフの生値スケール上の理想帯。
`YAxis domain=["dataMin","dataMax"]` だと理想帯が範囲外だと見えないため、**domain を理想帯込みに広げる**:
`YAxis` の domain を `["dataMin","dataMax"]` から、band 型は `[Math.min(dataMin, lo), Math.max(dataMax, hi)]`
相当にしたい。recharts では関数 domain を使う:
```tsx
<YAxis hide domain={([min, max]) => {
  if (metric.ideal.type === "band") return [Math.min(min, metric.ideal.lo), Math.max(max, metric.ideal.hi)];
  if (metric.ideal.good_line != null) return [Math.min(min, metric.ideal.good_line), Math.max(max, metric.ideal.good_line)];
  return [min, max];
}} />
```
両グラフの YAxis をこの関数 domain に差し替える。

---

## Task 7: 検証とデプロイ

- [ ] **Step 1: backend テスト + lint(Docker ワンオフ)**
```
docker run --rm -v "$PWD/backend:/app" -w /app python:3.12-slim bash -c \
  "pip install -q uv && uv pip install --system -e '.' --group dev && pytest -q && ruff check app/ tests/"
```
Expected: 全 PASS / All checks passed
- [ ] **Step 2: frontend ビルド** `cd frontend && npm run build` Expected: 成功
- [ ] **Step 3: コミット**(backend / frontend を論理単位で)
- [ ] **Step 4: デプロイ** `bin/up-mac.sh`。op セッションが切れていれば、ユーザーに
  `! export OP_BIOMETRIC_UNLOCK_ENABLED=false; eval "$(op signin)" && bin/up-mac.sh` を依頼。
- [ ] **Step 5: 疎通** `docker exec healthcare-backend sh -c "curl -s 'http://localhost:8000/api/trends?granularity=daily' | head -c 400"`
  で raw_series/ideal/achievement/regression が返ること。

---

## Self-Review

- **Spec coverage:** 達成度関数=Task1 / 回帰=Task2 / 生値取得=Task3 / API=Task4 / LLM=Task5 / frontend=Task6 / 検証・デプロイ=Task7。
- **Placeholder scan:** なし。
- **Type consistency:** `TrendMetricKey`(sleep/hrv/energy/load/weight/body_fat)が API の `metrics` キー・`ORDER`・`series_map` と一致。`IdealBand` の判別が API の `ideal.type` と一致。`achievement_prev_day_change` 名が API/TrendBadge/Sparkline で一致。
- **既知の注意:** YAxis domain を理想帯込みに広げる関数 domain を両グラフに適用(Task6 補足)。`_training_load` は private 参照だが既存 dashboard.py でも import 実績あり。
