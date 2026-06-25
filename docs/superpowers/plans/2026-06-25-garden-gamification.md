# Garden(理想の庭)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compass のギャップ連動で「良い行動」(運動・コーディング・瞑想・ジャーナリング・内省)を単一の総合草+streak として可視化する独立モジュール Garden を追加し、本番デプロイする。

**Architecture:** Compass と同じ独立モジュールパターン。`scoring/garden/` に純粋な判定ロジック、`ingest/github_sync.py` に GitHub 取込、`api/garden.py` に薄い API、`pages/Garden.tsx` に UI。健康スコア(recompute/DailyScore)とは混ぜない。Compass の `build_gap_report()` を一方向に読んで重みに使う。

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy(SQLite, WAL, マイグレーションなし=additive のみ)/ APScheduler / httpx。React + Vite + TanStack Query + Tailwind + Recharts。

## Global Constraints

- マイグレーションは存在しない。スキーマ変更は **additive かつ既存 SQLite 互換** のみ(新規テーブルだけ追加)。
- 日付ロジックは TZ-aware。当日は `app.scoring.timewindow.app_today()`(`Asia/Tokyo` 既定)。DB の datetime は **UTC naive**。
- チューニング定数は `config.py` に置く(臨床/個人の区分に従う)。scoring モジュールにハードコードしない。
- 新しい scoring ロジックには `backend/tests/` に単体テスト(DB/ネット不要を優先)。
- lint: `ruff check app/ tests/`(line-length 100, py312)。フロントは `npm run build`(tsc)+ `npm run lint`。
- UI 文言・コメントは日本語(既存トーン)。コード識別子は英語。
- backend テスト実行: `cd backend && .venv/bin/python -m pytest`。
- 既存パターン: API ルーターは `router = APIRouter()` でフルパス(`@router.get("/api/...")`、prefix なし)。手動ログ POST は Pydantic BaseModel + 任意 `ts_iso`。ingest は `httpx.Client(timeout=...)` + `raise_for_status()` + 例外は `logger.warning` で握って冪等。DB は `from app.db import session_scope`。

---

### Task 1: データモデル + config 定数

**Files:**
- Modify: `backend/app/models/health.py`(末尾に4テーブル追加)
- Modify: `backend/app/config.py`(garden 関連定数追加)
- Test: `backend/tests/test_garden_models.py`

**Interfaces:**
- Produces: SQLAlchemy モデル `GoodActionLog`, `GardenDaily`, `GithubContributionDaily`, `GardenConfig`(`app.models.health` からインポート可能)。`Settings.garden_catalog: list[dict]`, `Settings.garden_gap_gamma: float`, `Settings.garden_level_thresholds: list[float]`, `Settings.scheduler_github_sync_cron: str`, `Settings.scheduler_garden_recompute_cron: str`, `Settings.github_username: str | None`, `Settings.github_token: str | None`。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_garden_models.py
from datetime import datetime, date

from app.config import get_settings
from app.models.health import (
    GoodActionLog,
    GardenDaily,
    GithubContributionDaily,
    GardenConfig,
)


def test_garden_tables_have_expected_columns():
    assert GoodActionLog.__tablename__ == "good_action_log"
    assert GardenDaily.__tablename__ == "garden_daily"
    assert GithubContributionDaily.__tablename__ == "github_contribution_daily"
    assert GardenConfig.__tablename__ == "garden_config"
    # 列の存在確認
    GoodActionLog(ts=datetime(2026, 6, 25), kind="meditation", source="manual", value=1.0)
    GardenDaily(date=date(2026, 6, 25), intensity=0.0, level=0, contributions={}, streak_len=0)
    GithubContributionDaily(date=date(2026, 6, 25), commit_count=3)
    GardenConfig(id=1, github_username="octocat", github_token="x")


def test_garden_config_defaults_present():
    s = get_settings()
    kinds = {c["kind"] for c in s.garden_catalog}
    assert {"coding", "exercise", "meditation", "journaling", "reflection"} <= kinds
    assert s.garden_gap_gamma >= 0
    assert len(s.garden_level_thresholds) == 4
    # カタログの各エントリに必要キーがある
    for c in s.garden_catalog:
        assert {"kind", "source", "dimensions", "base", "evidence"} <= set(c)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_garden_models.py -q`
Expected: FAIL(ImportError: cannot import name 'GoodActionLog' …)

- [ ] **Step 3: モデル追加**

`backend/app/models/health.py` の末尾(最後のクラス定義の後)に追加。ファイル冒頭の import に `UniqueConstraint` があること、`from datetime import date, datetime` があることを確認(既存で使用済み)。

```python
class GoodActionLog(Base):
    """個別の良い行動イベント(手動ワンタップ & 自動取込)。"""

    __tablename__ = "good_action_log"
    __table_args__ = (UniqueConstraint("dedup_key", name="uq_good_action_dedup"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, index=True)  # UTC naive
    kind: Mapped[str] = mapped_column(String(32), index=True)  # meditation|journaling|reflection|...
    source: Mapped[str] = mapped_column(String(16))  # manual|apple_health|github|garmin
    value: Mapped[float] = mapped_column(Float, default=1.0)
    dedup_key: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 自動取込の冪等用
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)


class GardenDaily(Base):
    """日次の草1マス。冪等 upsert(再計算可能)。"""

    __tablename__ = "garden_daily"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    intensity: Mapped[float] = mapped_column(Float, default=0.0)
    level: Mapped[int] = mapped_column(Integer, default=0)  # 0-4
    contributions: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {kind: weighted_value}
    streak_len: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class GithubContributionDaily(Base):
    """GitHub の日次コミット数。"""

    __tablename__ = "github_contribution_daily"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    commit_count: Mapped[int] = mapped_column(Integer, default=0)
    repo_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class GardenConfig(Base):
    """GitHub 連携の認証情報(シングルトン id=1)。UI から設定。"""

    __tablename__ = "garden_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    github_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    github_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

- [ ] **Step 4: config 追加**

`backend/app/config.py` の `Settings` クラス内、Compass(`identity_*`)定義の近くに追加。`from pydantic import Field` は既存。

```python
    # --- Garden(ゲーミフィケーション)---
    # personal: 行動カタログ(理想像への紐付けを含むので個人依存)
    garden_catalog: list[dict] = Field(
        default_factory=lambda: [
            {"kind": "coding", "source": "github",
             "dimensions": ["self_direction", "proactivity", "ownership", "effectuation"],
             "base": 2.0, "evidence": "創造的アウトプット=founder 主体性の直接証拠"},
            {"kind": "exercise", "source": "garmin",
             "dimensions": ["risk_tolerance", "need_for_achievement"],
             "base": 1.5, "evidence": "有酸素運動→BDNF・実行機能 (Erickson 2011)"},
            {"kind": "meditation", "source": "manual",
             "dimensions": ["internal_locus", "growth_mindset"],
             "base": 1.2, "evidence": "瞑想→前頭前野・情動制御・HRV (Tang 2015)"},
            {"kind": "journaling", "source": "manual",
             "dimensions": ["growth_mindset", "internal_locus"],
             "base": 1.2, "evidence": "expressive writing (Pennebaker 1997)"},
            {"kind": "reflection", "source": "manual",
             "dimensions": ["growth_mindset", "ownership"],
             "base": 1.0, "evidence": "省察的実践 (Schön 1983)"},
        ]
    )
    # tuning: ギャップ連動の効き具合
    garden_gap_gamma: float = 1.0  # 盲点(gap最大)は重み最大 (1+gamma) 倍
    garden_level_thresholds: list[float] = Field(
        default_factory=lambda: [0.0, 1.0, 2.5, 4.5]
    )  # intensity→level 0-4 の境界
    # scheduler
    scheduler_github_sync_cron: str = "20 * * * *"
    scheduler_garden_recompute_cron: str = "25 * * * *"
    # GitHub 認証フォールバック(通常は DB GardenConfig 優先)
    github_username: str | None = None
    github_token: str | None = None
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_garden_models.py -q`
Expected: PASS(2 passed)

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/health.py backend/app/config.py backend/tests/test_garden_models.py
git commit -m "feat(garden): データモデルと config 定数を追加"
```

---

### Task 2: 純粋な判定ロジック(catalog + compute)

**Files:**
- Create: `backend/app/scoring/garden/__init__.py`(空)
- Create: `backend/app/scoring/garden/compute.py`
- Test: `backend/tests/test_garden_compute.py`

**Interfaces:**
- Consumes: `Settings.garden_catalog`, `garden_gap_gamma`, `garden_level_thresholds`(Task 1)。
- Produces:
  - `weight_factor(kind: str, catalog: list[dict], gaps: dict[str, float | None], gamma: float) -> float`
  - `bucket_level(intensity: float, thresholds: list[float]) -> int`
  - `compute_garden_day(active_kinds: set[str], catalog: list[dict], gaps: dict[str, float | None], gamma: float, thresholds: list[float]) -> dict`(返り値 `{"intensity": float, "level": int, "contributions": {kind: float}}`)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_garden_compute.py
from app.scoring.garden.compute import weight_factor, bucket_level, compute_garden_day

CATALOG = [
    {"kind": "coding", "source": "github",
     "dimensions": ["ownership", "proactivity"], "base": 2.0, "evidence": "x"},
    {"kind": "meditation", "source": "manual",
     "dimensions": ["internal_locus"], "base": 1.2, "evidence": "x"},
]


def test_weight_factor_uses_max_gap_of_dimensions():
    # gap は 0-100。ownership=80, proactivity=20 → max=80 → 1 + 1.0*0.8 = 1.8
    gaps = {"ownership": 80.0, "proactivity": 20.0}
    assert weight_factor("coding", CATALOG, gaps, gamma=1.0) == 1.8


def test_weight_factor_fallback_when_all_gaps_none():
    gaps = {"ownership": None, "proactivity": None}
    assert weight_factor("coding", CATALOG, gaps, gamma=1.0) == 1.0


def test_weight_factor_missing_dimension_in_gaps_is_ignored():
    # gaps に proactivity が無くても ownership だけで計算
    gaps = {"ownership": 50.0}
    assert weight_factor("coding", CATALOG, gaps, gamma=1.0) == 1.5


def test_bucket_level():
    th = [0.0, 1.0, 2.5, 4.5]
    assert bucket_level(0.0, th) == 0
    assert bucket_level(0.5, th) == 1
    assert bucket_level(1.0, th) == 1
    assert bucket_level(2.5, th) == 2
    assert bucket_level(3.0, th) == 3
    assert bucket_level(5.0, th) == 4


def test_compute_garden_day_sums_weighted_contributions():
    gaps = {"ownership": 80.0, "proactivity": 20.0, "internal_locus": 0.0}
    out = compute_garden_day(
        {"coding", "meditation"}, CATALOG, gaps, gamma=1.0, thresholds=[0.0, 1.0, 2.5, 4.5]
    )
    # coding: 2.0*1.8=3.6, meditation: 1.2*(1+0)=1.2 → 合計 4.8 → level 4
    assert round(out["intensity"], 2) == 4.8
    assert out["contributions"]["coding"] == 3.6
    assert out["contributions"]["meditation"] == 1.2
    assert out["level"] == 4


def test_compute_garden_day_empty():
    out = compute_garden_day(set(), CATALOG, {}, gamma=1.0, thresholds=[0.0, 1.0, 2.5, 4.5])
    assert out == {"intensity": 0.0, "level": 0, "contributions": {}}


def test_compute_ignores_unknown_kind():
    out = compute_garden_day(
        {"unknown"}, CATALOG, {}, gamma=1.0, thresholds=[0.0, 1.0, 2.5, 4.5]
    )
    assert out["intensity"] == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_garden_compute.py -q`
Expected: FAIL(ModuleNotFoundError: app.scoring.garden.compute)

- [ ] **Step 3: 実装**

`backend/app/scoring/garden/__init__.py` を空ファイルで作成。

```python
# backend/app/scoring/garden/compute.py
"""Garden の純粋な判定ロジック(DB・ネット非依存、単体テスト対象)。"""

from __future__ import annotations


def _catalog_entry(kind: str, catalog: list[dict]) -> dict | None:
    for c in catalog:
        if c["kind"] == kind:
            return c
    return None


def weight_factor(
    kind: str, catalog: list[dict], gaps: dict[str, float | None], gamma: float
) -> float:
    """行動 kind の重み係数。紐づく次元の最大 gap(0-100)で 1〜(1+gamma) 倍。

    紐づく次元が全て未測定(None)/欠落なら 1.0 にフォールバック。
    """
    entry = _catalog_entry(kind, catalog)
    if entry is None:
        return 1.0
    relevant = [gaps.get(d) for d in entry["dimensions"]]
    present = [g for g in relevant if g is not None]
    if not present:
        return 1.0
    max_gap = max(present)
    return 1.0 + gamma * (max_gap / 100.0)


def bucket_level(intensity: float, thresholds: list[float]) -> int:
    """intensity を 0-4 のレベルへ。thresholds=[t0,t1,t2,t3]。

    intensity<=t0 → 0、t0<..<=t1 → 1、t1<..<=t2 → 2、t2<..<=t3 → 3、t3< → 4。
    """
    if intensity <= thresholds[0]:
        return 0
    for i, t in enumerate(thresholds[1:], start=1):
        if intensity <= t:
            return i
    return len(thresholds)


def compute_garden_day(
    active_kinds: set[str],
    catalog: list[dict],
    gaps: dict[str, float | None],
    gamma: float,
    thresholds: list[float],
) -> dict:
    """その日に観測された行動種別からの草の強さを算出。"""
    contributions: dict[str, float] = {}
    for kind in active_kinds:
        entry = _catalog_entry(kind, catalog)
        if entry is None:
            continue
        contributions[kind] = round(entry["base"] * weight_factor(kind, catalog, gaps, gamma), 4)
    intensity = round(sum(contributions.values()), 4)
    return {
        "intensity": intensity,
        "level": bucket_level(intensity, thresholds),
        "contributions": contributions,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_garden_compute.py -q`
Expected: PASS(7 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/scoring/garden/__init__.py backend/app/scoring/garden/compute.py backend/tests/test_garden_compute.py
git commit -m "feat(garden): ギャップ連動の純粋な判定ロジック"
```

---

### Task 3: recompute(DB から行動を収集して GardenDaily upsert + streak)

**Files:**
- Create: `backend/app/scoring/garden/recompute.py`
- Test: `backend/tests/test_garden_recompute.py`

**Interfaces:**
- Consumes: `compute_garden_day`(Task 2)、モデル(Task 1)、`app.scoring.identity.store.build_gap_report`(`{"dimensions": [{"id", "gap", ...}], ...}`)、`app.db.session_scope`、`app.scoring.timewindow.app_today`。
- Produces:
  - `gaps_from_report(report: dict) -> dict[str, float | None]`
  - `active_kinds_for_date(session, target: date, catalog: list[dict]) -> set[str]`
  - `recompute_garden_for_date(session, target: date) -> GardenDaily`(GardenDaily を upsert して返す。streak も更新)

- [ ] **Step 1: Write the failing test**(in-memory SQLite を使う)

```python
# backend/tests/test_garden_recompute.py
from datetime import datetime, date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.health import (
    Base, GoodActionLog, Workout, GithubContributionDaily, GardenDaily,
)
from app.scoring.garden.recompute import (
    gaps_from_report, active_kinds_for_date, recompute_garden_for_date,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_gaps_from_report():
    report = {"dimensions": [
        {"id": "ownership", "gap": 80.0},
        {"id": "internal_locus", "gap": None},
    ]}
    assert gaps_from_report(report) == {"ownership": 80.0, "internal_locus": None}


def test_active_kinds_collects_manual_workout_and_github(session, monkeypatch):
    d = date(2026, 6, 25)
    # 手動ログ(瞑想)
    session.add(GoodActionLog(ts=datetime(2026, 6, 25, 1, 0), kind="meditation", source="manual"))
    # ワークアウト(運動)
    session.add(Workout(id="w1", source="garmin", start=datetime(2026, 6, 25, 9, 0), type="running"))
    # GitHub コミット
    session.add(GithubContributionDaily(date=d, commit_count=3))
    session.flush()
    catalog = [
        {"kind": "coding", "source": "github", "dimensions": [], "base": 2.0, "evidence": ""},
        {"kind": "exercise", "source": "garmin", "dimensions": [], "base": 1.5, "evidence": ""},
        {"kind": "meditation", "source": "manual", "dimensions": [], "base": 1.2, "evidence": ""},
    ]
    kinds = active_kinds_for_date(session, d, catalog)
    assert kinds == {"coding", "exercise", "meditation"}


def test_active_kinds_github_zero_commits_not_active(session):
    d = date(2026, 6, 25)
    session.add(GithubContributionDaily(date=d, commit_count=0))
    session.flush()
    catalog = [{"kind": "coding", "source": "github", "dimensions": [], "base": 2.0, "evidence": ""}]
    assert active_kinds_for_date(session, d, catalog) == set()


def test_recompute_upserts_and_computes_streak(session, monkeypatch):
    import app.scoring.garden.recompute as rc
    # gap レポートを固定(Compass 非依存にする)
    monkeypatch.setattr(rc, "build_gap_report", lambda s: {"dimensions": []})
    monkeypatch.setattr(rc, "get_settings", lambda: _FakeSettings())

    # 前日も草あり → streak 2 になること
    session.add(GardenDaily(date=date(2026, 6, 24), intensity=1.2, level=1,
                            contributions={"meditation": 1.2}, streak_len=1))
    session.add(GoodActionLog(ts=datetime(2026, 6, 25, 1, 0), kind="meditation", source="manual"))
    session.flush()

    row = recompute_garden_for_date(session, date(2026, 6, 25))
    assert row.date == date(2026, 6, 25)
    assert row.level >= 1
    assert row.streak_len == 2

    # 冪等: 再実行しても重複行を作らない
    recompute_garden_for_date(session, date(2026, 6, 25))
    count = session.query(GardenDaily).filter(GardenDaily.date == date(2026, 6, 25)).count()
    assert count == 1


class _FakeSettings:
    garden_catalog = [
        {"kind": "meditation", "source": "manual", "dimensions": ["internal_locus"],
         "base": 1.2, "evidence": ""},
    ]
    garden_gap_gamma = 1.0
    garden_level_thresholds = [0.0, 1.0, 2.5, 4.5]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_garden_recompute.py -q`
Expected: FAIL(ModuleNotFoundError: app.scoring.garden.recompute)

- [ ] **Step 3: 実装**

```python
# backend/app/scoring/garden/recompute.py
"""DB から当日の行動を収集し GardenDaily を再計算・upsert する。"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.health import (
    GardenDaily, GithubContributionDaily, GoodActionLog, Workout,
)
from app.scoring.identity.store import build_gap_report


def gaps_from_report(report: dict) -> dict[str, float | None]:
    """build_gap_report の出力を {dimension_id: gap} へ。"""
    return {d["id"]: d.get("gap") for d in report.get("dimensions", [])}


def _day_bounds(target: date) -> tuple[datetime, datetime]:
    """target 日(ローカル基準だが DB は UTC naive)の素朴な [start, end)。

    単一ユーザー・Asia/Tokyo 運用で、当日判定は app_today() 基準のため
    UTC naive の ts をそのまま日付一致で扱う(既存の手動ログ系と同じ素朴さ)。
    """
    start = datetime(target.year, target.month, target.day)
    return start, start + timedelta(days=1)


def active_kinds_for_date(session: Session, target: date, catalog: list[dict]) -> set[str]:
    """その日に観測された行動種別の集合。"""
    sources = {c["kind"]: c["source"] for c in catalog}
    start, end = _day_bounds(target)
    active: set[str] = set()

    # 手動 / apple_health 由来の GoodActionLog
    log_kinds = session.execute(
        select(GoodActionLog.kind).where(
            GoodActionLog.ts >= start, GoodActionLog.ts < end
        ).distinct()
    ).scalars().all()
    active.update(log_kinds)

    # GitHub: commit_count>0 → coding
    gh = session.get(GithubContributionDaily, target)
    if gh is not None and (gh.commit_count or 0) > 0:
        for kind, src in sources.items():
            if src == "github":
                active.add(kind)

    # Garmin: その日に Workout があれば exercise
    workout_exists = session.execute(
        select(func.count()).select_from(Workout).where(
            Workout.start >= start, Workout.start < end
        )
    ).scalar_one()
    if workout_exists:
        for kind, src in sources.items():
            if src == "garmin":
                active.add(kind)

    # カタログに無い kind は除外
    return {k for k in active if k in sources}


def _streak_len(session: Session, target: date, has_today: bool) -> int:
    if not has_today:
        return 0
    length = 1
    cursor = target - timedelta(days=1)
    while True:
        row = session.get(GardenDaily, cursor)
        if row is not None and row.intensity > 0:
            length += 1
            cursor -= timedelta(days=1)
        else:
            break
    return length


def recompute_garden_for_date(session: Session, target: date) -> GardenDaily:
    from app.scoring.garden.compute import compute_garden_day

    settings = get_settings()
    catalog = settings.garden_catalog
    gaps = gaps_from_report(build_gap_report(session))
    active = active_kinds_for_date(session, target, catalog)
    result = compute_garden_day(
        active, catalog, gaps,
        settings.garden_gap_gamma, settings.garden_level_thresholds,
    )

    row = session.get(GardenDaily, target)
    if row is None:
        row = GardenDaily(date=target)
        session.add(row)
    row.intensity = result["intensity"]
    row.level = result["level"]
    row.contributions = result["contributions"]
    row.updated_at = datetime.utcnow()
    row.streak_len = _streak_len(session, target, result["intensity"] > 0)
    session.flush()
    return row
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_garden_recompute.py -q`
Expected: PASS(4 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/scoring/garden/recompute.py backend/tests/test_garden_recompute.py
git commit -m "feat(garden): 当日の行動収集と GardenDaily 再計算・streak"
```

---

### Task 4: GitHub 取込(ingest/github_sync.py)

**Files:**
- Create: `backend/app/ingest/github_sync.py`
- Test: `backend/tests/test_github_sync.py`

**Interfaces:**
- Consumes: `GithubContributionDaily`, `GardenConfig`(Task 1)、`app.db.session_scope`、`get_settings`。
- Produces:
  - `resolve_github_credentials(session) -> tuple[str | None, str | None]`(DB 優先、settings フォールバック)
  - `parse_contribution_calendar(payload: dict) -> dict[date, int]`(GraphQL レスポンス → {date: commit数})
  - `sync_github(session, *, days: int = 60) -> dict`(取得して upsert、認証なしは no-op)
  - `async def github_sync_job() -> dict`(scheduler エントリ。`session_scope` を開いて `sync_github` 実行)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_github_sync.py
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.health import Base, GardenConfig, GithubContributionDaily
from app.ingest.github_sync import (
    parse_contribution_calendar, resolve_github_credentials, sync_github,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


SAMPLE = {
    "data": {"viewer": {"contributionsCollection": {"contributionCalendar": {"weeks": [
        {"contributionDays": [
            {"date": "2026-06-24", "contributionCount": 0},
            {"date": "2026-06-25", "contributionCount": 5},
        ]},
    ]}}}}
}


def test_parse_contribution_calendar():
    out = parse_contribution_calendar(SAMPLE)
    assert out == {date(2026, 6, 24): 0, date(2026, 6, 25): 5}


def test_resolve_credentials_prefers_db(session):
    session.add(GardenConfig(id=1, github_username="dbuser", github_token="dbtok"))
    session.flush()
    assert resolve_github_credentials(session) == ("dbuser", "dbtok")


def test_resolve_credentials_none_when_unset(session):
    assert resolve_github_credentials(session) == (None, None)


def test_sync_github_noop_without_credentials(session):
    out = sync_github(session)
    assert out["status"] == "skipped"


def test_sync_github_upserts(session, monkeypatch):
    session.add(GardenConfig(id=1, github_username="octocat", github_token="tok"))
    session.flush()
    import app.ingest.github_sync as gs
    monkeypatch.setattr(gs, "_fetch_calendar", lambda user, token, days: SAMPLE)
    out = sync_github(session, days=30)
    assert out["status"] == "ok"
    row = session.get(GithubContributionDaily, date(2026, 6, 25))
    assert row.commit_count == 5
    # 冪等
    sync_github(session, days=30)
    assert session.query(GithubContributionDaily).filter_by(date=date(2026, 6, 25)).count() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_github_sync.py -q`
Expected: FAIL(ModuleNotFoundError)

- [ ] **Step 3: 実装**

```python
# backend/app/ingest/github_sync.py
"""GitHub のコミット履歴(contribution calendar)を日次で取り込む。"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import httpx
import structlog
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import session_scope
from app.models.health import GardenConfig, GithubContributionDaily

logger = structlog.get_logger(__name__)

_GRAPHQL_URL = "https://api.github.com/graphql"
_QUERY = """
query($from: DateTime!, $to: DateTime!) {
  viewer {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""


def resolve_github_credentials(session: Session) -> tuple[str | None, str | None]:
    cfg = session.get(GardenConfig, 1)
    if cfg is not None and cfg.github_token:
        return cfg.github_username, cfg.github_token
    s = get_settings()
    return s.github_username, s.github_token


def parse_contribution_calendar(payload: dict) -> dict[date, int]:
    weeks = (
        payload.get("data", {})
        .get("viewer", {})
        .get("contributionsCollection", {})
        .get("contributionCalendar", {})
        .get("weeks", [])
    )
    out: dict[date, int] = {}
    for w in weeks:
        for d in w.get("contributionDays", []):
            out[date.fromisoformat(d["date"])] = int(d.get("contributionCount", 0))
    return out


def _fetch_calendar(username: str | None, token: str, days: int) -> dict | None:
    to = datetime.now(UTC)
    frm = to - timedelta(days=days)
    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.post(
                _GRAPHQL_URL,
                headers={"Authorization": f"bearer {token}"},
                json={"query": _QUERY, "variables": {"from": frm.isoformat(), "to": to.isoformat()}},
            )
            r.raise_for_status()
            return r.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("github_fetch_failed", error=str(exc))
        return None


def sync_github(session: Session, *, days: int = 60) -> dict:
    username, token = resolve_github_credentials(session)
    if not token:
        return {"status": "skipped", "reason": "no_credentials"}
    payload = _fetch_calendar(username, token, days)
    if payload is None:
        return {"status": "error"}
    calendar = parse_contribution_calendar(payload)
    upserted = 0
    for d, count in calendar.items():
        row = session.get(GithubContributionDaily, d)
        if row is None:
            row = GithubContributionDaily(date=d)
            session.add(row)
        row.commit_count = count
        row.updated_at = datetime.utcnow()
        upserted += 1
    session.flush()
    logger.info("github_sync_done", days=days, upserted=upserted)
    return {"status": "ok", "upserted": upserted}


async def github_sync_job() -> dict:
    with session_scope() as session:
        return sync_github(session)
```

注: `structlog` は既存 ingest で使用済み(`garmin_sync.py` 参照)。インポート名が異なる場合は既存に合わせる。

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_github_sync.py -q`
Expected: PASS(5 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingest/github_sync.py backend/tests/test_github_sync.py
git commit -m "feat(garden): GitHub contribution calendar の取込"
```

---

### Task 5: scheduler ジョブ登録 + garden_recompute_job

**Files:**
- Modify: `backend/app/scheduler.py`(lazy import + 2 ジョブ追加)
- Create: `backend/app/scoring/garden/jobs.py`(`garden_recompute_job`)
- Test: `backend/tests/test_garden_jobs.py`

**Interfaces:**
- Consumes: `recompute_garden_for_date`(Task 3)、`session_scope`、`app_today`、`sync_github`/`github_sync_job`(Task 4)、`Settings.scheduler_github_sync_cron`/`scheduler_garden_recompute_cron`。
- Produces: `async def garden_recompute_job() -> dict`。scheduler に `github_sync` と `garden_recompute` ジョブが登録される。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_garden_jobs.py
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.health import Base, GoodActionLog, GardenDaily
from datetime import datetime


@pytest.mark.asyncio
async def test_garden_recompute_job_runs(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sess = Session(engine)
    sess.add(GoodActionLog(ts=datetime(2026, 6, 25, 1, 0), kind="meditation", source="manual"))
    sess.commit()

    import app.scoring.garden.jobs as jobs
    from contextlib import contextmanager

    @contextmanager
    def fake_scope():
        yield sess

    monkeypatch.setattr(jobs, "session_scope", fake_scope)
    monkeypatch.setattr(jobs, "app_today", lambda: date(2026, 6, 25))
    monkeypatch.setattr(jobs, "build_gap_report", lambda s: {"dimensions": []}, raising=False)

    out = await jobs.garden_recompute_job()
    assert out["status"] == "ok"
    assert sess.get(GardenDaily, date(2026, 6, 25)) is not None
```

注: `build_gap_report` は `recompute` 側で参照される。jobs はそれを呼ぶだけなので、monkeypatch は `app.scoring.garden.recompute.build_gap_report` に当てる必要がある場合は `raising=True` で対象モジュールを指定する。テストが赤→緑になるよう実装後に調整可。

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_garden_jobs.py -q`
Expected: FAIL(ModuleNotFoundError: app.scoring.garden.jobs)

- [ ] **Step 3: jobs.py 実装**

```python
# backend/app/scoring/garden/jobs.py
"""Garden の scheduler ジョブ。"""

from __future__ import annotations

import structlog

from app.db import session_scope
from app.scoring.garden.recompute import recompute_garden_for_date
from app.scoring.timewindow import app_today

logger = structlog.get_logger(__name__)


async def garden_recompute_job() -> dict:
    today = app_today()
    with session_scope() as session:
        row = recompute_garden_for_date(session, today)
        result = {"status": "ok", "date": today.isoformat(), "level": row.level,
                  "intensity": row.intensity, "streak": row.streak_len}
    logger.info("garden_recompute_done", **result)
    return result
```

- [ ] **Step 4: scheduler.py に登録**

`backend/app/scheduler.py` の `setup_scheduler()` 内、既存の `add_job` 群の近く・lazy import 群に追加。

```python
    # lazy import 群に追加
    from app.ingest.github_sync import github_sync_job
    from app.scoring.garden.jobs import garden_recompute_job

    # add_job 群に追加
    scheduler.add_job(
        github_sync_job,
        _parse_cron(settings.scheduler_github_sync_cron),
        id="github_sync",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=600,
    )
    scheduler.add_job(
        garden_recompute_job,
        _parse_cron(settings.scheduler_garden_recompute_cron),
        id="garden_recompute",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=600,
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_garden_jobs.py -q`
Expected: PASS(1 passed)。`pytest-asyncio` が無い場合は既存テストの async パターン(`test_identity_*` 等)に合わせる。

- [ ] **Step 6: Commit**

```bash
git add backend/app/scoring/garden/jobs.py backend/app/scheduler.py backend/tests/test_garden_jobs.py
git commit -m "feat(garden): scheduler に github_sync と garden_recompute を登録"
```

---

### Task 6: API(api/garden.py)+ ルーター登録

**Files:**
- Create: `backend/app/api/garden.py`
- Modify: `backend/app/main.py`(import + include_router)
- Test: `backend/tests/test_garden_api.py`

**Interfaces:**
- Consumes: `recompute_garden_for_date`, `sync_github`(任意即時実行), `build_gap_report`, `gaps_from_report`, モデル, `session_scope`, `app_today`, `get_settings`。
- Produces(HTTP):
  - `GET /api/garden` → `{date, grid, streak, today, catalog, weakest_hint, github}`
  - `POST /api/garden/log` body `{kind, note?, ts_iso?}` → `{today}`
  - `POST /api/garden/config` body `{github_username, github_token}` → `{connected, username}`

- [ ] **Step 1: Write the failing test**(FastAPI TestClient、DB は一時ファイル or 既存の conftest パターンに合わせる)

```python
# backend/tests/test_garden_api.py
from fastapi.testclient import TestClient

from app.main import create_app


def test_garden_get_returns_shape(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    app = create_app()
    client = TestClient(app)
    r = client.get("/api/garden")
    assert r.status_code == 200
    body = r.json()
    assert {"date", "grid", "streak", "today", "catalog", "weakest_hint", "github"} <= set(body)
    assert isinstance(body["grid"], list)
    assert body["github"]["connected"] is False


def test_garden_log_then_grid_has_today(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    app = create_app()
    client = TestClient(app)
    r = client.post("/api/garden/log", json={"kind": "meditation"})
    assert r.status_code == 200
    assert "meditation" in r.json()["today"]["contributions"]


def test_garden_config_saves_username(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    app = create_app()
    client = TestClient(app)
    r = client.post("/api/garden/config",
                    json={"github_username": "octocat", "github_token": "tok"})
    assert r.status_code == 200
    assert r.json() == {"connected": True, "username": "octocat"}
    # token は返さない
    assert "github_token" not in r.json()
```

注: 既存の API テスト(`test_*_api` があれば)の DB 初期化パターン(conftest の fixture / `APP_DATA_DIR` env)に合わせること。無ければ上記 `tmp_path` + env で可。`create_app` のシグネチャは `app/main.py` を確認。

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_garden_api.py -q`
Expected: FAIL(404 / ImportError)

- [ ] **Step 3: 実装**

```python
# backend/app/api/garden.py
"""Garden(理想の庭)API。判定は scoring/garden に委譲し、ハンドラは薄く保つ。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import get_settings
from app.db import session_scope
from app.models.health import GardenConfig, GardenDaily, GoodActionLog
from app.scoring.garden.recompute import (
    gaps_from_report, recompute_garden_for_date,
)
from app.scoring.identity.store import build_gap_report
from app.scoring.timewindow import app_today

router = APIRouter()

_GRID_DAYS = 371  # 約53週


class GardenLogIn(BaseModel):
    kind: str
    note: str | None = None
    ts_iso: str | None = None


class GardenConfigIn(BaseModel):
    github_username: str | None = None
    github_token: str | None = None


def _today_payload(row: GardenDaily | None) -> dict:
    if row is None:
        return {"level": 0, "intensity": 0.0, "contributions": {}, "actions": []}
    contributions = row.contributions or {}
    return {
        "level": row.level,
        "intensity": row.intensity,
        "contributions": contributions,
        "actions": list(contributions.keys()),
    }


@router.get("/api/garden")
async def get_garden() -> dict:
    settings = get_settings()
    today = app_today()
    start = today - timedelta(days=_GRID_DAYS)
    with session_scope() as session:
        rows = (
            session.query(GardenDaily)
            .filter(GardenDaily.date >= start)
            .order_by(GardenDaily.date)
            .all()
        )
        grid = [
            {"date": r.date.isoformat(), "level": r.level,
             "intensity": r.intensity, "contributions": r.contributions or {}}
            for r in rows
        ]
        today_row = session.get(GardenDaily, today)
        streak = today_row.streak_len if today_row else 0

        # weakest_hint: gap 最大の次元に効く行動
        report = build_gap_report(session)
        gaps = gaps_from_report(report)
        weakest_hint = None
        present = {k: v for k, v in gaps.items() if v is not None}
        if present:
            top_dim = max(present, key=present.get)
            kinds = [c["kind"] for c in settings.garden_catalog if top_dim in c["dimensions"]]
            dim_name = next(
                (d.get("name") for d in report.get("dimensions", []) if d["id"] == top_dim),
                top_dim,
            )
            if kinds:
                weakest_hint = {"dimension_id": top_dim, "name": dim_name, "kinds": kinds}

        cfg = session.get(GardenConfig, 1)
        github = {"connected": bool(cfg and cfg.github_token),
                  "username": cfg.github_username if cfg else None}

        catalog = [
            {"kind": c["kind"], "source": c["source"], "evidence": c["evidence"],
             "dimensions": c["dimensions"]}
            for c in settings.garden_catalog
        ]
        today_payload = _today_payload(today_row)

    return {
        "date": today.isoformat(),
        "grid": grid,
        "streak": streak,
        "today": today_payload,
        "catalog": catalog,
        "weakest_hint": weakest_hint,
        "github": github,
    }


@router.post("/api/garden/log")
async def add_garden_log(body: GardenLogIn) -> dict:
    if body.ts_iso:
        ts = datetime.fromisoformat(body.ts_iso)
        if ts.tzinfo is not None:
            ts = ts.astimezone(UTC).replace(tzinfo=None)
    else:
        ts = datetime.now(UTC).replace(tzinfo=None)
    target = app_today() if not body.ts_iso else ts.date()
    with session_scope() as session:
        session.add(GoodActionLog(ts=ts, kind=body.kind, source="manual", value=1.0, note=body.note))
        session.flush()
        row = recompute_garden_for_date(session, target)
        payload = _today_payload(row)
    return {"today": payload}


@router.post("/api/garden/config")
async def set_garden_config(body: GardenConfigIn) -> dict:
    with session_scope() as session:
        cfg = session.get(GardenConfig, 1)
        if cfg is None:
            cfg = GardenConfig(id=1)
            session.add(cfg)
        cfg.github_username = body.github_username
        if body.github_token:
            cfg.github_token = body.github_token
        cfg.updated_at = datetime.utcnow()
        session.flush()
        connected = bool(cfg.github_token)
        username = cfg.github_username
    return {"connected": connected, "username": username}
```

- [ ] **Step 4: main.py に登録**

`backend/app/main.py`:
- import 群(`from app.api import ...`)に `from app.api import garden as garden_api` を追加。
- `create_app()` の include_router 群に `app.include_router(garden_api.router)` を追加。

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_garden_api.py -q`
Expected: PASS(3 passed)

- [ ] **Step 6: 全 backend テスト + lint**

Run: `cd backend && .venv/bin/python -m pytest -q && .venv/bin/python -m ruff check app/ tests/`
Expected: 全 PASS、lint クリーン

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/garden.py backend/app/main.py backend/tests/test_garden_api.py
git commit -m "feat(garden): API エンドポイントとルーター登録"
```

---

### Task 7: フロント api.ts(型 + wrapper)

**Files:**
- Modify: `frontend/src/lib/api.ts`(型と `api.*` メソッド追加)

**Interfaces:**
- Produces(TS):
  - 型 `GardenGridCell`, `GardenCatalogItem`, `GardenResponse`, `GardenToday`
  - `api.garden(): Promise<GardenResponse>`
  - `api.gardenLog(kind: string, opts?: {note?: string; ts_iso?: string}): Promise<{today: GardenToday}>`
  - `api.gardenConfig(github_username: string, github_token: string): Promise<{connected: boolean; username: string | null}>`

- [ ] **Step 1: 型を追加**(`api.ts` の型定義群の近く、例えば Identity 型の後)

```typescript
export type GardenGridCell = {
  date: string;
  level: number;
  intensity: number;
  contributions: Record<string, number>;
};

export type GardenToday = {
  level: number;
  intensity: number;
  contributions: Record<string, number>;
  actions: string[];
};

export type GardenCatalogItem = {
  kind: string;
  source: string;
  evidence: string;
  dimensions: string[];
};

export type GardenResponse = {
  date: string;
  grid: GardenGridCell[];
  streak: number;
  today: GardenToday;
  catalog: GardenCatalogItem[];
  weakest_hint: { dimension_id: string; name: string; kinds: string[] } | null;
  github: { connected: boolean; username: string | null };
};
```

- [ ] **Step 2: `api` オブジェクトにメソッド追加**(`export const api = { ... }` 内)

```typescript
  garden: () => request<GardenResponse>("/api/garden"),
  gardenLog: (kind: string, opts?: { note?: string; ts_iso?: string }) =>
    request<{ today: GardenToday }>("/api/garden/log", {
      method: "POST",
      body: JSON.stringify({ kind, ...opts }),
    }),
  gardenConfig: (github_username: string, github_token: string) =>
    request<{ connected: boolean; username: string | null }>("/api/garden/config", {
      method: "POST",
      body: JSON.stringify({ github_username, github_token }),
    }),
```

- [ ] **Step 3: 型チェック**

Run: `cd frontend && npm run build`
Expected: tsc がエラーなく通る(この時点では未使用型の警告は出ない=export 済み)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat(garden): フロント API 型と wrapper"
```

---

### Task 8: Garden ページ + ルーティング

**Files:**
- Create: `frontend/src/pages/Garden.tsx`
- Modify: `frontend/src/App.tsx`(`#garden` ルート追加)

**Interfaces:**
- Consumes: `api.garden`, `api.gardenLog`, `api.gardenConfig`, 型(Task 7)。
- Produces: `export function GardenPage({ onBack }: { onBack: () => void })`。

- [ ] **Step 1: GardenPage 実装**

```tsx
// frontend/src/pages/Garden.tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type GardenGridCell } from "../lib/api";

const LEVEL_BG = ["bg-slate-800", "bg-emerald-900", "bg-emerald-700", "bg-emerald-500", "bg-emerald-300"];
const KIND_LABEL: Record<string, string> = {
  coding: "コーディング", exercise: "運動", meditation: "瞑想",
  journaling: "ジャーナリング", reflection: "内省",
};

function ContributionGrid({ grid }: { grid: GardenGridCell[] }) {
  const byDate = new Map(grid.map((c) => [c.date, c]));
  // 53週 × 7日。最終日(今日)を右下に。
  const days: string[] = [];
  const last = grid.length ? grid[grid.length - 1].date : new Date().toISOString().slice(0, 10);
  const end = new Date(last + "T00:00:00");
  for (let i = 370; i >= 0; i--) {
    const d = new Date(end);
    d.setDate(end.getDate() - i);
    days.push(d.toISOString().slice(0, 10));
  }
  const weeks: string[][] = [];
  for (let i = 0; i < days.length; i += 7) weeks.push(days.slice(i, i + 7));
  return (
    <div className="flex gap-[3px] overflow-x-auto pb-2">
      {weeks.map((week, wi) => (
        <div key={wi} className="flex flex-col gap-[3px]">
          {week.map((d) => {
            const cell = byDate.get(d);
            const level = cell?.level ?? 0;
            return (
              <div
                key={d}
                title={`${d}: ${cell ? Object.keys(cell.contributions).map((k) => KIND_LABEL[k] ?? k).join(", ") || "—" : "—"}`}
                className={`h-[11px] w-[11px] rounded-sm ${LEVEL_BG[level]}`}
              />
            );
          })}
        </div>
      ))}
    </div>
  );
}

export function GardenPage({ onBack }: { onBack: () => void }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["garden"], queryFn: api.garden });
  const logMut = useMutation({
    mutationFn: (kind: string) => api.gardenLog(kind),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["garden"] }),
  });
  const [user, setUser] = useState("");
  const [token, setToken] = useState("");
  const cfgMut = useMutation({
    mutationFn: () => api.gardenConfig(user, token),
    onSuccess: () => { setToken(""); qc.invalidateQueries({ queryKey: ["garden"] }); },
  });

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4">
      <button onClick={onBack} className="text-sm text-slate-400">← 戻る</button>
      <h1 className="text-xl font-bold">理想の庭</h1>
      {q.isLoading && <p>読み込み中…</p>}
      {q.isError && <p className="text-red-400">取得に失敗しました</p>}
      {q.data && (
        <>
          <div className="rounded-lg bg-slate-900 p-4">
            <div className="mb-2 flex items-baseline justify-between">
              <span className="text-sm text-slate-400">連続</span>
              <span className="text-2xl font-bold text-emerald-400">{q.data.streak}日</span>
            </div>
            <ContributionGrid grid={q.data.grid} />
          </div>

          {q.data.weakest_hint && (
            <div className="rounded-lg bg-slate-900 p-4 text-sm">
              <span className="text-slate-400">今日効く行動: </span>
              <span className="font-semibold">{q.data.weakest_hint.name}</span>
              <span className="text-slate-400"> に効く </span>
              {q.data.weakest_hint.kinds.map((k) => KIND_LABEL[k] ?? k).join("・")}
              <span className="text-slate-400"> が濃く出ます</span>
            </div>
          )}

          <div className="rounded-lg bg-slate-900 p-4">
            <p className="mb-2 text-sm text-slate-400">今日の行動を記録</p>
            <div className="flex flex-wrap gap-2">
              {q.data.catalog.filter((c) => c.source === "manual").map((c) => (
                <button
                  key={c.kind}
                  disabled={logMut.isPending}
                  onClick={() => logMut.mutate(c.kind)}
                  className="rounded-full bg-emerald-700 px-3 py-1 text-sm hover:bg-emerald-600 disabled:opacity-50"
                >
                  + {KIND_LABEL[c.kind] ?? c.kind}
                </button>
              ))}
            </div>
            {q.data.today.actions.length > 0 && (
              <p className="mt-2 text-xs text-slate-500">
                今日: {q.data.today.actions.map((k) => KIND_LABEL[k] ?? k).join("・")}
              </p>
            )}
          </div>

          <div className="rounded-lg bg-slate-900 p-4">
            <p className="mb-2 text-sm text-slate-400">
              GitHub 連携 {q.data.github.connected ? `(${q.data.github.username})` : "(未接続)"}
            </p>
            <div className="flex flex-col gap-2 sm:flex-row">
              <input
                value={user} onChange={(e) => setUser(e.target.value)}
                placeholder="username"
                className="rounded bg-slate-800 px-2 py-1 text-sm"
              />
              <input
                value={token} onChange={(e) => setToken(e.target.value)}
                placeholder="personal access token" type="password"
                className="flex-1 rounded bg-slate-800 px-2 py-1 text-sm"
              />
              <button
                disabled={cfgMut.isPending || !token}
                onClick={() => cfgMut.mutate()}
                className="rounded bg-slate-700 px-3 py-1 text-sm hover:bg-slate-600 disabled:opacity-50"
              >
                保存
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
```

注: 色クラス・カードの見た目は既存ページ(Identity.tsx / Today.tsx)のトーンに合わせて微調整してよい。Tailwind の動的クラス(`LEVEL_BG[level]`)は文字列が静的に列挙されているのでパージされない。

- [ ] **Step 2: App.tsx にルート追加**

`frontend/src/App.tsx`:
- `import { GardenPage } from "./pages/Garden";` を追加。
- `type View = "today" | "debug" | "identity" | "garden";`
- `viewFromHash` に `if (window.location.hash === "#garden") return "garden";` を追加。
- 描画分岐に `view === "garden" ? (<GardenPage onBack={() => { window.location.hash = ""; }} />) :` を追加。

- [ ] **Step 3: ビルド + lint**

Run: `cd frontend && npm run build && npm run lint`
Expected: tsc / vite ビルド成功、eslint クリーン

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/Garden.tsx frontend/src/App.tsx
git commit -m "feat(garden): 理想の庭ページとルーティング"
```

---

### Task 9: Today ページにミニ草 + streak

**Files:**
- Modify: `frontend/src/pages/Today.tsx`(ミニ草バッジ + `#garden` への導線)

**Interfaces:**
- Consumes: `api.garden`(Task 7)。

- [ ] **Step 1: ミニ草コンポーネントを Today に追加**

`Today.tsx` に以下のカードを追加(既存の `useQuery` 群の近く)。直近約12週のみ表示し、タップで `#garden` へ。

```tsx
// Today.tsx の import に追加
import { api, type GardenGridCell } from "../lib/api";

// コンポーネント内(他の useQuery の近く)
const gardenQ = useQuery({ queryKey: ["garden"], queryFn: api.garden });

// JSX(適切な位置に挿入)
{gardenQ.data && (
  <button
    onClick={() => (window.location.hash = "#garden")}
    className="w-full rounded-lg bg-slate-900 p-4 text-left"
  >
    <div className="mb-2 flex items-baseline justify-between">
      <span className="text-sm text-slate-400">理想の庭</span>
      <span className="text-lg font-bold text-emerald-400">{gardenQ.data.streak}日連続</span>
    </div>
    <div className="flex gap-[2px]">
      {gardenQ.data.grid.slice(-84).map((c: GardenGridCell) => (
        <div
          key={c.date}
          className={`h-2 w-2 rounded-sm ${
            ["bg-slate-800", "bg-emerald-900", "bg-emerald-700", "bg-emerald-500", "bg-emerald-300"][c.level]
          }`}
        />
      ))}
    </div>
  </button>
)}
```

注: 挿入位置と見た目は Today.tsx の既存レイアウトに合わせる。色配列は Garden.tsx と重複するが、小さなミニ表示用なのでローカル定義で可(YAGNI: 共通化は後回し)。

- [ ] **Step 2: ビルド + lint**

Run: `cd frontend && npm run build && npm run lint`
Expected: 成功・クリーン

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/Today.tsx
git commit -m "feat(garden): Today にミニ草+streak の導線"
```

---

### Task 10: 統合確認 → マージ → 本番デプロイ

**Files:** なし(検証・デプロイのみ)

- [ ] **Step 1: 全テスト + lint(backend / frontend)**

```bash
cd backend && .venv/bin/python -m pytest -q && .venv/bin/python -m ruff check app/ tests/
cd ../frontend && npm run build && npm run lint
```
Expected: 全 PASS、lint クリーン

- [ ] **Step 2: main へマージ**

```bash
cd /home/tsuyoshi/ghq/github.com/nagamine-git/healthcare
git checkout main && git merge --no-ff feat/garden-gamification -m "feat(garden): 理想の庭(ゲーミフィケーション)を追加"
```

- [ ] **Step 3: 本番デプロイ([[deploy-mechanism]] に従う)**

op 経由が自走できないため、既存の解決済み `.env.runtime` を再利用:
```bash
docker compose --env-file .env.runtime up -d --build backend frontend
```

- [ ] **Step 4: 疎通確認**

```bash
docker exec healthcare-backend curl -s localhost:8000/api/garden
```
Expected: JSON が返る(初回は grid 空・github.connected=false でも 200)。

- [ ] **Step 5: 動作確認の案内**

ユーザーに `https://healthcare.<tailnet>.ts.net/#garden` を開いてもらい、(1) ワンタップで瞑想等を記録して草が付くこと、(2) GitHub の username/token を設定パネルから保存 → 数分後(または手動で `github_sync` 実行)に gh 草が反映されることを確認してもらう。

GitHub token は `repo` または最低 `read:user` スコープの classic PAT、もしくは fine-grained PAT(contents:read 相当)。

---

## Self-Review

**1. Spec coverage:**
- §3 データモデル → Task 1 ✓
- §4 config → Task 1 ✓
- §5 判定ロジック(ギャップ連動) → Task 2(純粋)+ Task 3(収集) ✓
- §6 取り込み&ジョブ → Task 4(github)+ Task 5(scheduler/recompute job) ✓
- §6 瞑想 Apple Health → v1 は manual のみ(HAE に mindful 無しを確認済み)。catalog の meditation.source="manual" に確定 ✓
- §7 API → Task 6 ✓
- §8 フロント → Task 7/8/9 ✓
- §9 テスト → 各 Task に単体テスト + Task 10 統合 ✓
- §10 デプロイ → Task 10 ✓

**2. Placeholder scan:** コード step は全て実コードを記載。残る「実装時に確認」は (a) structlog の import 名、(b) API テストの DB 初期化 fixture、(c) pytest-asyncio の有無 — いずれも既存テスト/モジュールに同型の前例があり、実装者がそれに倣えば解決する範囲。

**3. Type consistency:**
- `weight_factor(kind, catalog, gaps, gamma)` / `compute_garden_day(active_kinds, catalog, gaps, gamma, thresholds)` は Task 2 定義と Task 3 呼び出しで一致 ✓
- `recompute_garden_for_date(session, target) -> GardenDaily` は Task 3/5/6 で一致 ✓
- `sync_github(session, *, days)` / `resolve_github_credentials(session)` / `parse_contribution_calendar(payload)` は Task 4 内で一致 ✓
- フロント型 `GardenResponse`(grid/streak/today/catalog/weakest_hint/github)は API §7 の返り値と一致 ✓
