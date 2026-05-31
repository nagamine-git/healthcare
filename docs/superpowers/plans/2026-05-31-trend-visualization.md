# 改善トレンドの可視化 — 実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 日次スコア(総合 + 6サブスコア)の前日比・前週比・トレンド方向を計算し、Today にバッジ表示、専用 Trends ビューで日次/週次グラフ表示し、LLM 助言にもトレンドを反映する。

**Architecture:** バックエンドに DB 非依存の純粋関数 `trends.py` を追加(計算)。`daily_score` を読む `/api/trends` エンドポイントと LLM の `recent_trends` payload が同じ計算関数を共有(DRY)。フロントは再利用可能な `TrendBadge` と専用 `Trends` ページを追加し、ハッシュルーティングで切替。

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy / pytest(backend), React 18 / TypeScript / recharts / Tailwind(frontend)。

---

## File Structure

- Create: `backend/app/scoring/trends.py` — DB 非依存のトレンド計算(純粋関数 + 定数)
- Create: `backend/tests/test_trends.py` — `trends.py` のユニットテスト
- Modify: `backend/app/api/dashboard.py` — `GET /api/trends` エンドポイント追加
- Modify: `backend/tests/test_dashboard_api.py` — `/api/trends` のテスト追加
- Modify: `backend/app/llm/client.py` — `_gather_recent_trends()` を追加し payload に注入
- Modify: `backend/app/llm/prompts.py` — `recent_trends` の説明をプロンプトに追加
- Modify: `backend/tests/test_llm.py` — `_gather_recent_trends()` のテスト追加
- Modify: `frontend/src/lib/api.ts` — トレンド型 + `api.trends()`
- Create: `frontend/src/components/TrendBadge.tsx` — 方向矢印 + 前日比バッジ
- Modify: `frontend/src/components/Sparkline.tsx` — `trend` prop を受けてバッジ表示
- Create: `frontend/src/pages/Trends.tsx` — 日次/週次トグル付き専用ビュー
- Modify: `frontend/src/pages/Today.tsx` — Sparkline にトレンドを渡す + Trends へのリンク
- Modify: `frontend/src/App.tsx` — `#trends` ルート追加

---

## Task 1: トレンド計算コア (`trends.py`)

**Files:**
- Create: `backend/app/scoring/trends.py`
- Test: `backend/tests/test_trends.py`

- [ ] **Step 1: 失敗するテストを書く**

`backend/tests/test_trends.py`:

```python
from __future__ import annotations

from datetime import date

from app.scoring import trends


def _series(values, start=date(2026, 5, 1)):
    from datetime import timedelta

    return [(start + timedelta(days=i), v) for i, v in enumerate(values)]


def test_compute_trend_improving():
    # 単調増加 → improving, 前日比 +2
    t = trends.compute_trend(_series([60, 62, 64, 66, 68, 70, 72, 74]))
    assert t["current"] == 74
    assert t["prev_day_change"] == 2
    assert t["direction"] == "improving"
    assert t["week_over_week"]["delta"] > 0


def test_compute_trend_declining():
    t = trends.compute_trend(_series([80, 78, 76, 74, 72, 70, 68, 66]))
    assert t["direction"] == "declining"
    assert t["prev_day_change"] == -2


def test_compute_trend_stable():
    t = trends.compute_trend(_series([70, 70, 70, 70, 70, 70, 70]))
    assert t["direction"] == "stable"


def test_compute_trend_too_few_points():
    t = trends.compute_trend(_series([70]))
    assert t["direction"] is None
    assert t["prev_day_change"] is None
    assert t["week_over_week"] is None
    assert t["current"] == 70


def test_compute_trend_higher_is_better_false_inverts():
    # 増加系列でも higher_is_better=False なら declining
    t = trends.compute_trend(_series([60, 62, 64, 66, 68, 70, 72]), higher_is_better=False)
    assert t["direction"] == "declining"


def test_compute_trend_skips_none():
    t = trends.compute_trend(_series([60, None, 64, None, 68, 70, 72, 74]))
    # None を除外して計算できる
    assert t["current"] == 74
    assert t["direction"] == "improving"


def test_weekly_average_groups_by_monday():
    # 2026-05-04 は月曜
    s = _series([10, 20, 30, 40, 50, 60, 70], start=date(2026, 5, 4))  # 月〜日
    s += _series([100], start=date(2026, 5, 11))  # 翌週月曜
    out = trends.weekly_average(s)
    assert out[0] == {"date": "2026-05-04", "value": 40.0}  # (10..70)/7
    assert out[1] == {"date": "2026-05-11", "value": 100.0}


def test_series_by_column_and_build_metrics():
    # rows: (date, total, sleep_sub, hrv_sub, bb_sub, load_sub, weight_sub, body_fat_sub)
    from datetime import timedelta

    rows = []
    for i in range(8):
        d = date(2026, 5, 1) + timedelta(days=i)
        rows.append((d, 60 + i * 2, 50 + i, None, 70, 80, 75, 90))
    by_col = trends.series_by_column(rows)
    assert len(by_col["total"]) == 8
    assert len(by_col["bb_sub"]) == 0  # 全て None

    metrics = trends.build_metrics(by_col, granularity="daily")
    assert metrics["total"]["label"] == "総合スコア"
    assert metrics["total"]["direction"] == "improving"
    assert metrics["total"]["higher_is_better"] is True
    assert len(metrics["total"]["series"]) == 8
    # 全 None の指標は series 空 / direction None
    assert metrics["body_battery"]["series"] == []
    assert metrics["body_battery"]["direction"] is None
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `cd backend && .venv/bin/pytest tests/test_trends.py -v`
Expected: FAIL(`ModuleNotFoundError: app.scoring.trends` / `AttributeError`)

- [ ] **Step 3: `trends.py` を実装**

`backend/app/scoring/trends.py`:

```python
"""日次スコア系列から前日比・前週比・トレンド方向を計算する DB 非依存の純粋関数群。

入力は ``(date, value)`` の系列。出力は JSON 化可能な dict。
DB アクセスは呼び出し側 (dashboard / llm) が担い、ここはロジックに専念する。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Literal

Direction = Literal["improving", "stable", "declining"]

# 傾きを系列レンジで正規化した値がこの閾値未満なら "stable" とみなす。
STABLE_THRESHOLD = 0.02

# daily_score テーブルの取得列順 (エンドポイント / LLM が同順で SELECT する)。
SCORE_COLUMNS: list[str] = [
    "total",
    "sleep_sub",
    "hrv_sub",
    "bb_sub",
    "load_sub",
    "weight_sub",
    "body_fat_sub",
]

# API レスポンスキー / 表示ラベル / daily_score の列名。
TREND_METRICS: list[tuple[str, str, str]] = [
    ("total", "総合スコア", "total"),
    ("sleep", "睡眠", "sleep_sub"),
    ("hrv", "自律神経", "hrv_sub"),
    ("body_battery", "エネルギー", "bb_sub"),
    ("load", "運動負荷", "load_sub"),
    ("weight", "体重", "weight_sub"),
    ("body_fat", "体脂肪率", "body_fat_sub"),
]


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _linear_slope(values: list[float]) -> float | None:
    """等間隔 x=0..n-1 に対する最小二乗法の傾き。2 点未満や分散ゼロは None。"""
    n = len(values)
    if n < 2:
        return None
    mean_x = (n - 1) / 2
    mean_y = sum(values) / n
    num = sum((i - mean_x) * (v - mean_y) for i, v in enumerate(values))
    den = sum((i - mean_x) ** 2 for i in range(n))
    if den == 0:
        return None
    return num / den


def _direction(values: list[float], higher_is_better: bool) -> Direction | None:
    slope = _linear_slope(values)
    if slope is None:
        return None
    rng = max(values) - min(values)
    norm = slope / rng if rng > 1e-9 else 0.0
    if not higher_is_better:
        norm = -norm
    if norm > STABLE_THRESHOLD:
        return "improving"
    if norm < -STABLE_THRESHOLD:
        return "declining"
    return "stable"


def _clean(series: list[tuple[date, float | None]]) -> list[tuple[date, float]]:
    """None を除外し日付昇順にそろえる。"""
    pts = [(d, v) for d, v in series if v is not None]
    pts.sort(key=lambda p: p[0])
    return pts


def compute_trend(
    series: list[tuple[date, float | None]],
    *,
    higher_is_better: bool = True,
    direction_window: int = 7,
) -> dict[str, Any]:
    """日次系列からトレンド指標を計算する。"""
    pts = _clean(series)
    values = [v for _, v in pts]

    current = values[-1] if values else None
    prev_day_change = values[-1] - values[-2] if len(values) >= 2 else None

    week_over_week: dict[str, Any] | None = None
    if len(values) >= 8:
        recent = _mean(values[-7:])
        prior = _mean(values[-14:-7])
        if recent is not None and prior is not None:
            delta = recent - prior
            pct = (delta / prior * 100) if prior != 0 else None
            week_over_week = {
                "delta": round(delta, 2),
                "pct": round(pct, 1) if pct is not None else None,
            }

    direction = (
        _direction(values[-direction_window:], higher_is_better)
        if len(values) >= 2
        else None
    )

    return {
        "current": round(current, 2) if current is not None else None,
        "prev_day_change": round(prev_day_change, 2)
        if prev_day_change is not None
        else None,
        "week_over_week": week_over_week,
        "direction": direction,
    }


def daily_series(series: list[tuple[date, float | None]]) -> list[dict[str, Any]]:
    return [{"date": d.isoformat(), "value": round(v, 2)} for d, v in _clean(series)]


def weekly_average(series: list[tuple[date, float | None]]) -> list[dict[str, Any]]:
    """カレンダー週 (月曜始め) ごとの平均。各点の date は週開始 (月曜)。"""
    buckets: dict[date, list[float]] = defaultdict(list)
    for d, v in _clean(series):
        monday = d - timedelta(days=d.weekday())
        buckets[monday].append(v)
    out: list[dict[str, Any]] = []
    for monday in sorted(buckets):
        vals = buckets[monday]
        out.append({"date": monday.isoformat(), "value": round(sum(vals) / len(vals), 2)})
    return out


def series_by_column(
    rows: list[tuple[Any, ...]],
) -> dict[str, list[tuple[date, float]]]:
    """``(date, *SCORE_COLUMNS)`` の行列を列ごとの (date, value) 系列に展開する。"""
    by_col: dict[str, list[tuple[date, float]]] = {c: [] for c in SCORE_COLUMNS}
    for row in rows:
        d = row[0]
        for offset, col in enumerate(SCORE_COLUMNS, start=1):
            v = row[offset]
            if v is not None:
                by_col[col].append((d, v))
    return by_col


def build_metrics(
    by_col: dict[str, list[tuple[date, float]]],
    *,
    granularity: str = "daily",
) -> dict[str, Any]:
    """列系列から API レスポンス用の metrics dict を組む。全指標 higher_is_better=True。"""
    metrics: dict[str, Any] = {}
    for key, label, col in TREND_METRICS:
        series = by_col.get(col, [])
        trend = compute_trend(series, higher_is_better=True)
        trend["series"] = (
            weekly_average(series) if granularity == "weekly" else daily_series(series)
        )
        metrics[key] = {"label": label, "higher_is_better": True, **trend}
    return metrics
```

- [ ] **Step 4: テストが通ることを確認**

Run: `cd backend && .venv/bin/pytest tests/test_trends.py -v`
Expected: PASS(8 tests)

- [ ] **Step 5: ruff チェック**

Run: `cd backend && .venv/bin/ruff check app/scoring/trends.py tests/test_trends.py`
Expected: All checks passed

- [ ] **Step 6: コミット**

```bash
git add backend/app/scoring/trends.py backend/tests/test_trends.py
git commit -m "feat(scoring): trend computation (prev-day/week-over-week/direction)"
```

---

## Task 2: `/api/trends` エンドポイント

**Files:**
- Modify: `backend/app/api/dashboard.py`(末尾に追加)
- Test: `backend/tests/test_dashboard_api.py`

- [ ] **Step 1: 失敗するテストを書く**

`backend/tests/test_dashboard_api.py` の末尾に追加:

```python
def test_trends_endpoint_daily(app_client):
    from app.db import session_scope

    today = date.today()
    with session_scope() as session:
        # 8 日分、total を単調増加で seed
        for i in range(8):
            d = today - timedelta(days=7 - i)
            session.add(
                DailyScore(
                    date=d,
                    total=60 + i * 2,
                    sleep_sub=70,
                    hrv_sub=65,
                    bb_sub=80,
                    load_sub=85,
                    weight_sub=75,
                    body_fat_sub=90,
                    version="v1",
                    computed_at=datetime.now(UTC).replace(tzinfo=None),
                )
            )

    resp = app_client.get("/api/trends", params={"granularity": "daily", "days": 28})
    assert resp.status_code == 200
    body = resp.json()
    assert body["granularity"] == "daily"
    total = body["metrics"]["total"]
    assert total["label"] == "総合スコア"
    assert total["current"] == 74
    assert total["prev_day_change"] == 2
    assert total["direction"] == "improving"
    assert total["higher_is_better"] is True
    assert len(total["series"]) == 8
    # 全指標キーが揃う
    assert set(body["metrics"].keys()) == {
        "total", "sleep", "hrv", "body_battery", "load", "weight", "body_fat",
    }


def test_trends_endpoint_weekly(app_client):
    from app.db import session_scope

    today = date.today()
    with session_scope() as session:
        for i in range(14):
            d = today - timedelta(days=13 - i)
            session.add(
                DailyScore(
                    date=d,
                    total=70.0,
                    version="v1",
                    computed_at=datetime.now(UTC).replace(tzinfo=None),
                )
            )

    resp = app_client.get("/api/trends", params={"granularity": "weekly", "days": 28})
    assert resp.status_code == 200
    body = resp.json()
    assert body["granularity"] == "weekly"
    # 週平均なので series 点数は日数より少ない (高々 3 週)
    assert len(body["metrics"]["total"]["series"]) <= 3
    assert all(p["value"] == 70.0 for p in body["metrics"]["total"]["series"])
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `cd backend && .venv/bin/pytest tests/test_dashboard_api.py -k trends -v`
Expected: FAIL(404 もしくは KeyError)

- [ ] **Step 3: エンドポイントを実装**

`backend/app/api/dashboard.py` の `timeseries()` 関数定義の直後(`def _score_to_dict` の前)に追加:

```python
@router.get("/api/trends")
async def trends(
    granularity: str = Query(default="daily"),
    days: int = Query(default=28, ge=7, le=365),
) -> dict[str, Any]:
    from app.scoring import trends as trend_calc

    end = _today()
    start = end - timedelta(days=days)
    with session_scope() as session:
        rows = session.execute(
            select(
                DailyScore.date,
                DailyScore.total,
                DailyScore.sleep_sub,
                DailyScore.hrv_sub,
                DailyScore.bb_sub,
                DailyScore.load_sub,
                DailyScore.weight_sub,
                DailyScore.body_fat_sub,
            )
            .where(DailyScore.date >= start)
            .order_by(DailyScore.date)
        ).all()

    by_col = trend_calc.series_by_column(rows)
    metrics = trend_calc.build_metrics(by_col, granularity=granularity)
    return {
        "granularity": granularity,
        "generated_at": _utc_iso(datetime.now(UTC).replace(tzinfo=None)),
        "metrics": metrics,
    }
```

注: `select` の列順は `trends.SCORE_COLUMNS`(`total, sleep_sub, hrv_sub, bb_sub, load_sub, weight_sub, body_fat_sub`)と完全一致させること。`series_by_column` がこの順序前提で展開する。

- [ ] **Step 4: テストが通ることを確認**

Run: `cd backend && .venv/bin/pytest tests/test_dashboard_api.py -k trends -v`
Expected: PASS(2 tests)

- [ ] **Step 5: 既存テスト一式が壊れていないこと**

Run: `cd backend && .venv/bin/pytest tests/test_dashboard_api.py -v`
Expected: 全 PASS

- [ ] **Step 6: コミット**

```bash
git add backend/app/api/dashboard.py backend/tests/test_dashboard_api.py
git commit -m "feat(api): GET /api/trends daily/weekly score trends"
```

---

## Task 3: LLM 助言にトレンドを反映

**Files:**
- Modify: `backend/app/llm/client.py`
- Modify: `backend/app/llm/prompts.py`
- Test: `backend/tests/test_llm.py`

- [ ] **Step 1: 失敗するテストを書く**

`backend/tests/test_llm.py` の末尾に追加:

```python
def test_gather_recent_trends_builds_directions(db_engine):
    from datetime import UTC, date, datetime, timedelta

    from app.db import session_scope
    from app.llm.client import _gather_recent_trends
    from app.models import DailyScore

    today = date.today()
    with session_scope() as session:
        for i in range(8):
            d = today - timedelta(days=7 - i)
            session.add(
                DailyScore(
                    date=d,
                    total=60 + i * 2,
                    sleep_sub=70,
                    version="v1",
                    computed_at=datetime.now(UTC).replace(tzinfo=None),
                )
            )

    trends = _gather_recent_trends(today)
    assert trends["total"]["direction"] == "improving"
    assert "week_over_week" in trends["total"]
    # コンパクト化のため series は含めない
    assert "series" not in trends["total"]
```

(`db_engine` fixture が `app.db` のグローバルエンジンを初期化するため、`session_scope` がそのまま使える。既存 `test_llm.py` のテストと同じ前提。)

- [ ] **Step 2: テストが失敗することを確認**

Run: `cd backend && .venv/bin/pytest tests/test_llm.py -k recent_trends -v`
Expected: FAIL(`ImportError: cannot import name '_gather_recent_trends'`)

- [ ] **Step 3: `client.py` に `_gather_recent_trends` を実装**

`backend/app/llm/client.py` の `_gather_baselines` 関数の直後に追加:

```python
def _gather_recent_trends(target: date_type, days: int = 28) -> dict[str, Any]:
    """直近のスコアトレンド (方向 + 前日比 + 前週比) を LLM 用にコンパクトに返す。

    series は重いので落とし、direction / prev_day_change / week_over_week のみ渡す。
    dashboard の /api/trends と同じ計算 (app.scoring.trends) を共有する。
    """
    from app.scoring import trends as trend_calc

    start = target - timedelta(days=days)
    with session_scope() as session:
        rows = session.execute(
            select(
                DailyScore.date,
                DailyScore.total,
                DailyScore.sleep_sub,
                DailyScore.hrv_sub,
                DailyScore.bb_sub,
                DailyScore.load_sub,
                DailyScore.weight_sub,
                DailyScore.body_fat_sub,
            )
            .where(DailyScore.date >= start, DailyScore.date <= target)
            .order_by(DailyScore.date)
        ).all()

    by_col = trend_calc.series_by_column(rows)
    metrics = trend_calc.build_metrics(by_col, granularity="daily")
    return {
        key: {
            "direction": m["direction"],
            "prev_day_change": m["prev_day_change"],
            "week_over_week": m["week_over_week"],
        }
        for key, m in metrics.items()
    }
```

- [ ] **Step 4: payload に注入**

`backend/app/llm/client.py` の `generate_advice_for_date` 内、`baselines = _gather_baselines(target)` の直前に1行追加:

```python
    today_payload["recent_trends"] = _gather_recent_trends(target)
    baselines = _gather_baselines(target)
```

- [ ] **Step 5: プロンプトにトレンドの説明を追加**

`backend/app/llm/prompts.py` の `SYSTEM_PERSONA_TEMPLATE` 内、「# スコアの意味 (0–100)」セクションの直前に次のブロックを挿入:

```python
# 最近のトレンド (``recent_trends``)
- 各スコアの ``direction`` (improving=改善傾向 / stable=横ばい / declining=低下傾向)、
  ``prev_day_change`` (前日比)、``week_over_week`` (直近7日平均 vs その前7日平均の差) を渡す
- **focus か rationale で、最も顕著なトレンドに 1 つ触れる** (例: 「総合スコアは1週間で改善傾向」
  「自律神経が低下傾向なので回復を優先」)。良い変化は前向きに、悪化は原因と対策を 1 文で
- トレンドへの言及は **1 箇所まで**。羅列せず、本日の方針に直結するものだけを選ぶ
```

- [ ] **Step 6: テストが通ることを確認**

Run: `cd backend && .venv/bin/pytest tests/test_llm.py -k recent_trends -v`
Expected: PASS

- [ ] **Step 7: backend 全テスト + ruff**

Run: `cd backend && .venv/bin/pytest -q && .venv/bin/ruff check app/ tests/`
Expected: 全 PASS / All checks passed

- [ ] **Step 8: コミット**

```bash
git add backend/app/llm/client.py backend/app/llm/prompts.py backend/tests/test_llm.py
git commit -m "feat(llm): feed recent score trends into advice prompt"
```

---

## Task 4: フロント API クライアントと型

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: 型と関数を追加**

`frontend/src/lib/api.ts` の `TimeseriesResponse` 型定義の直後に追加:

```typescript
export type TrendDirection = "improving" | "stable" | "declining";

export type TrendMetric = {
  label: string;
  current: number | null;
  higher_is_better: boolean;
  prev_day_change: number | null;
  week_over_week: { delta: number; pct: number | null } | null;
  direction: TrendDirection | null;
  series: TimeseriesPoint[];
};

export type TrendMetricKey =
  | "total"
  | "sleep"
  | "hrv"
  | "body_battery"
  | "load"
  | "weight"
  | "body_fat";

export type TrendsResponse = {
  granularity: "daily" | "weekly";
  generated_at: string | null;
  metrics: Record<TrendMetricKey, TrendMetric>;
};
```

`api` オブジェクト(`timeseries:` の行の直後)に追加:

```typescript
  trends: (granularity: "daily" | "weekly" = "daily", days = 28) =>
    request<TrendsResponse>(
      `/api/trends?granularity=${granularity}&days=${days}`,
    ),
```

- [ ] **Step 2: 型チェック**

Run: `cd frontend && npm run typecheck`
Expected: エラーなし(未使用警告は可)

- [ ] **Step 3: コミット**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat(frontend): trends API client + types"
```

---

## Task 5: `TrendBadge` と Sparkline 統合 / Today バッジ

**Files:**
- Create: `frontend/src/components/TrendBadge.tsx`
- Modify: `frontend/src/components/Sparkline.tsx`
- Modify: `frontend/src/pages/Today.tsx`

- [ ] **Step 1: `TrendBadge` を作成**

`frontend/src/components/TrendBadge.tsx`:

```tsx
import type { TrendDirection } from "../lib/api";

type Props = {
  direction: TrendDirection | null;
  prevDayChange?: number | null;
  unit?: string;
  formatChange?: (v: number) => string;
};

const ARROW: Record<TrendDirection, string> = {
  improving: "↗",
  stable: "→",
  declining: "↘",
};

const LABEL: Record<TrendDirection, string> = {
  improving: "改善",
  stable: "横ばい",
  declining: "低下",
};

// 全指標 higher_is_better=true 前提: improving=緑 / declining=赤 / stable=灰
const COLOR: Record<TrendDirection, string> = {
  improving: "text-emerald-400",
  stable: "text-slate-400",
  declining: "text-rose-400",
};

export function TrendBadge({ direction, prevDayChange, unit, formatChange }: Props) {
  if (!direction) {
    return <span className="text-xs text-slate-600">—</span>;
  }
  const changeText =
    prevDayChange != null && prevDayChange !== 0
      ? `${prevDayChange > 0 ? "+" : ""}${
          formatChange ? formatChange(prevDayChange) : prevDayChange.toFixed(1)
        }${unit ?? ""}`
      : null;
  return (
    <span className={`flex items-center gap-1 text-xs ${COLOR[direction]}`}>
      <span className="tabular-nums">{changeText}</span>
      <span aria-label={LABEL[direction]}>
        {ARROW[direction]} {LABEL[direction]}
      </span>
    </span>
  );
}
```

- [ ] **Step 2: `Sparkline` に `trend` prop を追加**

`frontend/src/components/Sparkline.tsx` を次のように変更。

`import` 行の下に追加:

```tsx
import { TrendBadge } from "./TrendBadge";
import type { TrendMetric } from "../lib/api";
```

`Props` 型に `trend?: TrendMetric;` を追加:

```tsx
type Props = {
  label: string;
  data: TimeseriesPoint[];
  formatter?: (v: number) => string;
  color?: string;
  trend?: TrendMetric;
};
```

関数シグネチャを `({ label, data, formatter, color = "#34d399", trend }: Props)` にし、
ヘッダ部分(`<div className="mb-2 flex ...">` ブロック)を次に置換:

```tsx
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <span className="text-xs uppercase tracking-wider text-slate-400">
          {label}
        </span>
        {trend ? (
          <TrendBadge direction={trend.direction} prevDayChange={trend.prev_day_change} />
        ) : (
          <span className="text-xs text-slate-500">
            {filtered.length > 0 ? `${filtered.length} 日` : ""}
          </span>
        )}
      </div>
```

- [ ] **Step 3: Today で trends を取得して Sparkline に渡す + Trends リンク**

`frontend/src/pages/Today.tsx`:

`hrvSeries` の `useQuery` 定義の直後に追加:

```tsx
  const trends = useQuery({
    queryKey: ["trends", "daily"],
    queryFn: () => api.trends("daily", 28),
  });
```

Sparkline セクション(`<section className="grid gap-3 ...">` 内)の 4 つの Sparkline に
`trend` を渡す:

```tsx
        <Sparkline
          label="総合スコア 14日"
          data={scoreSeries.data?.data ?? []}
          color="#34d399"
          trend={trends.data?.metrics.total}
        />
        <Sparkline
          label="睡眠時間 14日"
          data={sleepSeries.data?.data ?? []}
          color="#60a5fa"
          formatter={(v) => formatMinutes(v)}
          trend={trends.data?.metrics.sleep}
        />
        <Sparkline
          label="HRV 28日"
          data={hrvSeries.data?.data ?? []}
          color="#a78bfa"
          formatter={(v) => `${v.toFixed(0)} ms`}
          trend={trends.data?.metrics.hrv}
        />
        <Sparkline
          label="体重 28日"
          data={weightSeries.data?.data ?? []}
          color="#f472b6"
          formatter={(v) => `${v.toFixed(1)} kg`}
          trend={trends.data?.metrics.weight}
        />
```

ヘッダの日付 `<span>` の直後(`<span className="text-xs tabular-nums text-slate-500">{data.date}</span>` の直後)に、Trends ページへのリンクを追加:

```tsx
          <a
            href="#trends"
            className="rounded-lg bg-slate-800/70 px-2 py-1 text-xs text-slate-300 hover:bg-slate-700"
          >
            トレンド
          </a>
```

注: Sparkline の「睡眠時間」「HRV」「体重」は生実数値のグラフだが、`trend` は対応する
スコア(sleep_sub / hrv_sub / weight_sub)由来の方向を表す。バッジは「その指標のコンディションが
改善/低下しているか」を示す位置づけ(値の単位は出さず方向のみ)なので整合する。

- [ ] **Step 4: 型チェック**

Run: `cd frontend && npm run typecheck`
Expected: エラーなし

- [ ] **Step 5: コミット**

```bash
git add frontend/src/components/TrendBadge.tsx frontend/src/components/Sparkline.tsx frontend/src/pages/Today.tsx
git commit -m "feat(frontend): trend badges on Today sparklines + Trends link"
```

---

## Task 6: 専用 Trends ページ + ルーティング

**Files:**
- Create: `frontend/src/pages/Trends.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: `Trends` ページを作成**

`frontend/src/pages/Trends.tsx`:

```tsx
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../lib/api";
import type { TrendDirection, TrendMetric, TrendMetricKey } from "../lib/api";

type Props = {
  onBack?: () => void;
};

const ORDER: TrendMetricKey[] = [
  "total",
  "sleep",
  "hrv",
  "body_battery",
  "load",
  "weight",
  "body_fat",
];

const DIRECTION_LABEL: Record<TrendDirection, string> = {
  improving: "改善傾向",
  stable: "横ばい",
  declining: "低下傾向",
};

const DIRECTION_COLOR: Record<TrendDirection, string> = {
  improving: "text-emerald-400",
  stable: "text-slate-400",
  declining: "text-rose-400",
};

const LINE_COLOR = "#34d399";

function TrendCard({
  metric,
  granularity,
}: {
  metric: TrendMetric;
  granularity: "daily" | "weekly";
}) {
  const data = metric.series;
  const dir = metric.direction;
  const wow = metric.week_over_week;
  return (
    <div className="rounded-2xl bg-slate-900/70 p-4">
      <div className="mb-1 flex items-baseline justify-between">
        <span className="text-sm text-slate-200">{metric.label}</span>
        <span className="text-2xl font-light tabular-nums text-slate-100">
          {metric.current != null ? Math.round(metric.current) : "--"}
        </span>
      </div>
      <div className="mb-2 flex items-center justify-between text-xs">
        <span className={dir ? DIRECTION_COLOR[dir] : "text-slate-600"}>
          {dir ? DIRECTION_LABEL[dir] : "データ不足"}
        </span>
        <span className="text-slate-500">
          {metric.prev_day_change != null
            ? `前日比 ${metric.prev_day_change > 0 ? "+" : ""}${metric.prev_day_change.toFixed(1)}`
            : ""}
          {wow ? ` / 前週比 ${wow.delta > 0 ? "+" : ""}${wow.delta.toFixed(1)}` : ""}
        </span>
      </div>
      <div className="h-28">
        <ResponsiveContainer width="100%" height="100%">
          {granularity === "weekly" ? (
            <BarChart data={data}>
              <XAxis dataKey="date" hide />
              <YAxis hide domain={["dataMin", "dataMax"]} />
              <Tooltip
                contentStyle={{ backgroundColor: "#1e293b", border: "1px solid #334155", fontSize: 12 }}
                formatter={(v: number) => v.toFixed(1)}
              />
              <Bar dataKey="value" fill={LINE_COLOR} radius={[3, 3, 0, 0]} />
            </BarChart>
          ) : (
            <LineChart data={data}>
              <XAxis dataKey="date" hide />
              <YAxis hide domain={["dataMin", "dataMax"]} />
              <Tooltip
                contentStyle={{ backgroundColor: "#1e293b", border: "1px solid #334155", fontSize: 12 }}
                formatter={(v: number) => v.toFixed(1)}
              />
              <Line type="monotone" dataKey="value" stroke={LINE_COLOR} strokeWidth={2} dot={false} />
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
          <button
            onClick={onBack}
            className="rounded-lg bg-slate-800/70 px-2 py-1 text-xs text-slate-300 hover:bg-slate-700"
          >
            ← 戻る
          </button>
          <span className="text-sm text-slate-200">トレンド</span>
        </div>
        <div className="flex rounded-lg bg-slate-800/70 p-0.5 text-xs">
          <button
            onClick={() => setGranularity("daily")}
            className={`rounded-md px-3 py-1 ${
              granularity === "daily" ? "bg-slate-600 text-slate-100" : "text-slate-400"
            }`}
          >
            日次
          </button>
          <button
            onClick={() => setGranularity("weekly")}
            className={`rounded-md px-3 py-1 ${
              granularity === "weekly" ? "bg-slate-600 text-slate-100" : "text-slate-400"
            }`}
          >
            週次
          </button>
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

- [ ] **Step 2: `App.tsx` にルートを追加**

`frontend/src/App.tsx` を次に置換:

```tsx
import { useEffect, useState } from "react";
import { TodayPage } from "./pages/Today";
import { DebugPage } from "./pages/Debug";
import { TrendsPage } from "./pages/Trends";

type View = "today" | "debug" | "trends";

function viewFromHash(): View {
  if (window.location.hash === "#debug") return "debug";
  if (window.location.hash === "#trends") return "trends";
  return "today";
}

export default function App() {
  const [view, setView] = useState<View>(viewFromHash);

  useEffect(() => {
    const handler = () => setView(viewFromHash());
    window.addEventListener("hashchange", handler);
    return () => window.removeEventListener("hashchange", handler);
  }, []);

  if (view === "debug") {
    return (
      <DebugPage
        onBack={() => {
          window.location.hash = "";
        }}
      />
    );
  }

  if (view === "trends") {
    return (
      <TrendsPage
        onBack={() => {
          window.location.hash = "";
        }}
      />
    );
  }

  return <TodayPage onOpenDebug={() => (window.location.hash = "#debug")} />;
}
```

- [ ] **Step 3: 型チェック + 本番ビルド**

Run: `cd frontend && npm run build`
Expected: `tsc -b` エラーなし、`vite build` 成功(dist 生成)

- [ ] **Step 4: コミット**

```bash
git add frontend/src/pages/Trends.tsx frontend/src/App.tsx
git commit -m "feat(frontend): dedicated Trends page with daily/weekly toggle"
```

---

## Task 7: 検証とデプロイ

- [ ] **Step 1: backend 全テスト + lint**

Run: `cd backend && .venv/bin/pytest -q && .venv/bin/ruff check app/ tests/`
Expected: 全 PASS / All checks passed

- [ ] **Step 2: frontend ビルド**

Run: `cd frontend && npm run build`
Expected: 成功

- [ ] **Step 3: デプロイ**

Run: `bin/up.sh`(`op run` で secrets 解決 → `docker compose up -d --build`)
Expected: backend / frontend コンテナが起動。`/api/trends?granularity=daily` が 200 を返す。

注: `bin/up.sh` の実体(`op run` 認証や compose ファイル指定)を実行前に確認する。Mac 環境では
`bin/up-mac.sh` / `docker-compose.mac.yml` を使う可能性があるため、どれが現行のデプロイ手段かを
ユーザーに確認してから実行する。

---

## Self-Review

- **Spec coverage:** trends.py(計算)= Task 1 / `/api/trends`(日次・週次)= Task 2 /
  LLM 連携 = Task 3 / Today バッジ = Task 5 / 専用 Trends ビュー + ナビ = Task 6 /
  ビルド・デプロイ = Task 7。spec の全節に対応タスクあり。
- **Placeholder scan:** なし(全ステップに実コード/実コマンド)。
- **Type consistency:** `SCORE_COLUMNS` の順序を Task 2・Task 3 の SELECT 列順と一致。
  `TrendMetric` 型(api.ts)は `/api/trends` の各メトリクス形と一致。`TrendMetricKey` は
  `TREND_METRICS` のキー(total/sleep/hrv/body_battery/load/weight/body_fat)と一致。
