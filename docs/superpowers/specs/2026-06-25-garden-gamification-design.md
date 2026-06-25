# Garden(理想の庭)— ゲーミフィケーション設計

- 日付: 2026-06-25
- ステータス: 確定(実装着手可)
- 関連: [[compass-feature]](Compass = 価値観×マインドセット羅針盤)

## 1. 目的と背景

「いいことをしたら草を生やす」(GitHub の contribution graph 的)ゲーミフィケーション機能。
ただし「いいこと」を汎用的な健康習慣ではなく、**オーナーの理想像(Compass の founder
アーキタイプ)への前進度**で定義する。健康スコア(DailyScore)とは独立した第3の軸。

判定基準は二重:
- **包含基準**: エビデンスのある「脳・人生に良い行動」(運動・コーディング・瞑想・ジャーナリング等)
- **重み基準**: その行動が Compass で測った理想像のどの次元を前進させるか。
  いま薄い次元(盲点)を埋める行動ほど草が濃くなる(**ギャップ連動・適応的**)。

オーナーの自覚する盲点は「サラリーマンマインドが抜けない」こと。よって founder 的・起業的
次元(主体性・オーナーシップ等)のギャップが大きいと、コーディング等の草が濃く出る。

## 2. アーキテクチャ方針

Compass と同じ「独立モジュール」パターンを採用する。健康コンディション軸(recompute /
DailyScore)には混ぜない。Garden は内部で次を読む:
- Garmin 活動(既存テーブル)
- GitHub コミット(新規 ingest)
- ワンタップ手動ログ / Apple Health mindful minutes
- Compass の `build_gap_report()`(重み付けのため)

責務分離: **Garden = 行動の実行と可視化**、**Compass = 理想像の次元現在地の測定**。
Garden は Compass の次元現在地を更新しない(一方向の読み取りのみ)。

新規ファイル:
- `backend/app/scoring/garden/__init__.py`
- `backend/app/scoring/garden/recompute.py`(純粋関数 `recompute_garden_for_date`)
- `backend/app/scoring/garden/catalog.py`(カタログ正規化・dimension 解決ヘルパ)
- `backend/app/ingest/github_sync.py`
- `backend/app/api/garden.py`
- `backend/tests/test_garden_recompute.py`
- `backend/tests/test_github_sync.py`
- `frontend/src/pages/Garden.tsx`
- フロント既存への追記: `App.tsx`(`#garden` ルート), `lib/api.ts`(型 + wrapper),
  `pages/Today.tsx`(ミニ草 + streak)

## 3. データモデル(`models/health.py` に additive 追加)

```python
class GoodActionLog(Base):
    """個別の良い行動イベント(手動ワンタップ & 自動取込)。"""
    __tablename__ = "good_action_log"
    id: int (PK, autoincrement)
    ts: datetime              # UTC naive, index
    kind: str(32)             # exercise|coding|meditation|journaling|reflection|...
    source: str(16)           # manual|apple_health|github|garmin
    value: float              # 既定 1.0(分・回数などの量)
    dedup_key: str(64) | None # 自動取込の冪等用(unique index)。手動は None
    note: str(200) | None

class GardenDaily(Base):
    """日次の「草1マス」。冪等 upsert。再計算可能。"""
    __tablename__ = "garden_daily"
    date: date (PK)
    intensity: float          # 重み付け後の合計
    level: int                # 0-4(GitHub 風バケット)
    contributions: dict(JSON) # {kind: weighted_value}
    streak_len: int           # 当日から遡る intensity>0 連続日数
    updated_at: datetime

class GithubContributionDaily(Base):
    """GitHub の日次コミット数。"""
    __tablename__ = "github_contribution_daily"
    date: date (PK)
    commit_count: int
    repo_count: int | None
    updated_at: datetime

class GardenConfig(Base):
    """GitHub 連携の認証情報(シングルトン id=1)。UI から設定。"""
    __tablename__ = "garden_config"
    id: int (PK, default=1)
    github_username: str(64) | None
    github_token: str(255) | None   # 単一ユーザー・自ホスト・tailnet 内なので平文保存可
    updated_at: datetime
```

`db.create_all()` がスタートアップで実行される(マイグレーションなし)。全て新規テーブル
なので既存 SQLite と互換。

行動カタログ自体はテーブルではなく **config** に持つ(下記)。`GardenDaily` は
「その日のログ + Garmin 活動 + gh + gap 重み」から再計算する純粋関数の出力。streak と
表示性能のために保存する。

## 4. config(`config.py`)

```python
# personal — 行動カタログ(理想像への紐付けを含むので個人依存)
garden_catalog: list[dict] = [
  {"kind": "coding",     "source": "github",
   "dimensions": ["self_direction", "proactivity", "ownership", "effectuation"],
   "base": 2.0, "evidence": "創造的アウトプット = founder 主体性の直接証拠"},
  {"kind": "exercise",   "source": "garmin",
   "dimensions": ["risk_tolerance", "need_for_achievement"],
   "base": 1.5, "evidence": "有酸素運動 → BDNF・実行機能 (Erickson 2011)"},
  {"kind": "meditation", "source": "apple_health",   # なければ manual
   "dimensions": ["internal_locus", "growth_mindset"],
   "base": 1.2, "evidence": "瞑想 → 前頭前野・情動制御・HRV (Tang 2015)"},
  {"kind": "journaling", "source": "manual",
   "dimensions": ["growth_mindset", "internal_locus"],
   "base": 1.2, "evidence": "expressive writing (Pennebaker 1997)"},
  {"kind": "reflection", "source": "manual",
   "dimensions": ["growth_mindset", "ownership"],
   "base": 1.0, "evidence": "省察的実践 (Schon 1983)"},
]

# tuning — ギャップ連動の効き具合
garden_gap_gamma: float = 1.0               # 盲点(gap 最大)は重み最大 (1+gamma) 倍
garden_level_thresholds: list[float] = [0.0, 1.0, 2.5, 4.5]  # intensity→level の境界

# scheduler(既存パターンに合わせ settings 化)
scheduler_github_sync_cron: str = "20 * * * *"      # 毎時 20 分
scheduler_garden_recompute_cron: str = "25 * * * *" # 毎時 25 分(github_sync の後)
```

GitHub username/token は config ではなく **DB(`GardenConfig`)** に持ち UI から設定する。
config 側にプレースホルダのフォールバック(`github_username/github_token: str | None = None`)
だけ用意し、DB 優先で解決する。

## 5. 判定ロジック(`scoring/garden/recompute.py`)

純粋関数。DB・ネット不要でテスト可能(gap と当日入力を渡す形にする)。

```
weight_factor(action_kind) =
    1 + gamma * (max_gap_of_its_dimensions / 100)
    # gap は Compass build_gap_report() の dimension.gap(0-100、未測定は None)
    # action が複数次元に紐づく場合は最大 gap を採用(最も盲点に効く面を評価)
    # 全次元が gap=None(Compass 未測定)なら weight_factor = 1.0 にフォールバック

day_intensity = Σ_active_kinds ( base(kind) * weight_factor(kind) )
    # active_kinds = その日に観測された行動種別の集合

level = bucket(day_intensity, garden_level_thresholds)  # 0-4
    # intensity == 0 → 0、threshold[0] 超〜[1] → 1 … [3] 超 → 4

streak_len = 当日から遡って intensity>0 が続く日数
```

行動の収集(`recompute_garden_for_date(session, date)` 内):
- `GoodActionLog` の当日分(手動 + apple_health 取込)を kind 別に集約
- Garmin: 当日「運動した」と言える活動があれば `exercise` を active 化
  (既存の活動テーブルを参照。実装時に最適なソースを確認 — 例: アクティビティ/歩数/強度分)
- `GithubContributionDaily`: 当日 commit_count > 0 なら `coding` を active 化
- 同一 kind が複数ソースから来ても 1 回だけカウント

出力: `GardenDaily` を冪等 upsert(contributions に kind ごとの weighted_value を保存)。

## 6. 取り込み & ジョブ

### `ingest/github_sync.py`
- GitHub GraphQL `viewer.contributionsCollection.contributionCalendar` を token で取得し、
  日次 commit 数(`contributionDays`)を `GithubContributionDaily` に upsert。
- private リポも含むため token は `repo`/`read:user` 相当スコープ前提。
- httpx.Client + raise_for_status + 例外は logger.warning(既存 ingest と同じ冪等設計)。
- 認証情報は `GardenConfig`(DB)優先、無ければ settings フォールバック。未設定なら no-op で
  status を返す(gh 草は 0 マス表示)。

### `scheduler.py`(lazy import で 2 ジョブ追加)
- `github_sync_job`(`scheduler_github_sync_cron`)→ `garden_recompute_job`
  (`scheduler_garden_recompute_cron`、当日 + streak 更新)。
- coalesce=True, max_instances=1。

### 瞑想(Apple Health mindful minutes)
- 実装時に既存 HAE データに mindful minutes があるか確認。あれば取込ジョブ/パーサで
  `GoodActionLog(kind="meditation", source="apple_health", dedup_key=...)` を冪等投入。
- 無ければワンタップ(`source="manual"`)のみで運用。

## 7. API(`api/garden.py`)

```
GET  /api/garden
  → {
      date,                         # ISO
      grid: [{date, level, intensity, contributions}],  # 過去約 53 週
      streak,                       # 現在の連続日数
      today: {level, intensity, contributions, actions: [kind...]},
      catalog: [{kind, name, source, evidence, dimensions}],
      weakest_hint: {dimension_id, name, kinds: [...]} | null,  # 今日濃く出る行動
      github: {connected: bool, username: str | null},
    }

POST /api/garden/log            # ワンタップ手動記録
  body: {kind, note?, ts_iso?}
  → 当日再計算して today を返す

POST /api/garden/config         # GitHub 連携設定(UI から)
  body: {github_username, github_token}
  → {connected: true, username}  # token は返さない
  → 保存後に github_sync を 1 回即時実行して当日反映(任意)
```

API ハンドラは薄く保ち、計算は `scoring/garden/` に置く(CLAUDE.md の層分離)。

## 8. フロント(`pages/Garden.tsx`, `#garden`)

- `App.tsx` の `View` に `"garden"` を追加、`#garden` で表示。
- `lib/api.ts` に型(`GardenResponse` 他)と wrapper(`api.garden`, `api.gardenLog`,
  `api.gardenConfig`)を追加。
- GardenPage 構成:
  - **ContributionGrid**: GitHub 風ヒートマップ(過去約 1 年、level 0-4 で濃淡)
  - **StreakCard**: 現在の streak と今日の level
  - **今日のワンタップ**: カタログの manual 行動(瞑想・ジャーナリング・内省)ボタン群 →
    `gardenLog` mutation → grid 再取得
  - **WeakestHint**: 「今日は◯◯(盲点の次元)に効く行動が濃く出る」表示(ギャップ連動の可視化)
  - **GithubConfigPanel**: username / token 入力 → `gardenConfig` mutation(未接続時に目立たせる)
- `Today.tsx` にミニ草(直近数週)+ streak バッジを追加。
- 文言は日本語(既存トーンに合わせる)。

## 9. テスト方針

- `test_garden_recompute.py`: weight_factor(gap 連動)、level バケット、streak、複数ソース
  重複排除、Compass 未測定時のフォールバックを純粋関数として検証(DB/ネット不要)。
- `test_github_sync.py`: GraphQL レスポンスのパース → 日次 upsert、認証未設定時 no-op、
  httpx をモックして冪等性を確認。
- 既存スイートが落ちないこと(`uv run pytest`, `ruff check`)。
- フロント: `npm run build`(tsc) と `npm run lint` が通ること。

## 10. デプロイ

- `bin/up.sh`(1Password → `.env.runtime`)で `docker compose up -d --build`。
- 起動後 `db.create_all()` で新テーブル生成。
- ユーザーは GardenPage の設定パネルで GitHub username/token を入力 → 連携開始。
- 詳細手順は [[deploy-mechanism]] に従う(op アクセス不可時は `.env.runtime` 再利用)。

## 11. YAGNI(やらないこと)

- 多レーン草(理想の側面別)— v1 は単一総合草。
- レベル/XP メーター — v1 は草 + streak のみ。
- 実行意図(if-then)遂行の草化 — Compass 側に既存。将来 active シグナルとして合流余地。
- バッジ・通知での煽り — 既存 notification とは独立。将来検討。
