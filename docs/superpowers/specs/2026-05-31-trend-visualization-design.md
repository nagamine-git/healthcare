# 改善トレンドの可視化 — 設計

日付: 2026-05-31

## 目的

ユーザーが「毎日だんだん数値が良くなっているか」を、日ベース・週ベースで一目で把握できるようにする。
既存の日次スコア (`daily_score`) と各メトリクスは蓄積済みのため、新しい計測ではなく
「既存値の前日比・前週比・トレンド方向」を計算・表示することで実現する。

## スコープ

対象メトリクス: `daily_score` テーブルの **総合スコア (`total`) と 6 サブスコア**
(`sleep_sub`, `hrv_sub`, `bb_sub`, `load_sub`, `weight_sub`, `body_fat_sub`)。
いずれも 0–100 で、**高いほど良い**。総合スコアを主役に、各サブ指標も並べて表示する。

スコアに統一する理由:
- 「数値が良くなっているか」を最も直接的に表すのは 0–100 のスコア(高いほど良い)である。
- 全メトリクスが `daily_score` の単一テーブルから同一クエリで取れ、計算・色付けロジックが統一される。
- 生の実数値(体重 kg、HRV ms、睡眠時間など)は既存の Today ページの Sparkline で継続表示する。
  トレンドビューはスコアベースで「改善しているか」を見せる役割に特化する。

非目標(YAGNI): 予測モデル(ARIMA/Prophet)、異常検出アラート、年単位ダッシュボード、
生実数値のトレンド専用ページ化。

## 用語: 週の定義

- **トレンド方向判定**: ローリング7日(直近7日 vs その前7日)。日々更新され反応が早い。
- **週次グラフ**: カレンダー週(月曜始め, JST)ごとの平均値の系列。週単位の達成感が見える。
- 両者を併用する。

## アーキテクチャ

### バックエンド

**新規 `backend/app/scoring/trends.py`** — DB に依存しない純粋関数群。
`(date, value)` の日次系列を入力に、以下を算出する。

- `prev_day_change`: 末尾の値と、その1つ前の値の差分(`current - prev`)
- `week_over_week`: 直近7日平均 vs その前7日平均(差分 + %)
- `direction`: 直近7日(7点)の線形回帰の傾きから `improving` / `stable` / `declining` を判定
- `weekly_series`: カレンダー週(月曜始め, JST)ごとの平均値の系列

対象は全てスコア(高いほど良い)なので、`direction` は「傾き > 0 → improving」で統一。
将来 higher_is_better=false の指標を足せるよう、関数は `higher_is_better: bool = True` 引数を取り、
false のとき方向を反転させる(本実装では常に True で呼ぶ)。

`stable` の閾値: 傾きを系列の値レンジ(max-min、ゼロ割回避に下限を設ける)で正規化し、
|正規化傾き| が `STABLE_THRESHOLD`(= 0.02)未満なら `stable`。

**新規エンドポイント `GET /api/trends`** (`backend/app/api/dashboard.py`):
- クエリ: `?granularity=daily|weekly`(デフォルト daily)、`?days=N`(日次系列の長さ、デフォルト28)
- `daily_score` から `date, total, sleep_sub, hrv_sub, bb_sub, load_sub, weight_sub, body_fat_sub`
  を1クエリで取得し、列ごとに `trends.compute_trend()` を適用する。
- 返却(メトリクスごと、キーは `total`/`sleep`/`hrv`/`body_battery`/`load`/`weight`/`body_fat`):
  ```json
  {
    "granularity": "daily",
    "generated_at": "...",
    "metrics": {
      "total": {
        "label": "総合スコア",
        "current": 78.0,
        "higher_is_better": true,
        "prev_day_change": 5.0,
        "week_over_week": { "delta": 3.2, "pct": 4.3 },
        "direction": "improving",
        "series": [{ "date": "2026-05-04", "value": 70.0 }, ...]
      },
      "sleep": { "label": "睡眠", ... },
      "hrv": { "label": "自律神経", ... }
    }
  }
  ```
- `granularity=weekly` のとき `series` はカレンダー週平均(各点の `date` は週開始日)。
  `current` / `prev_day_change` / `week_over_week` / `direction` は日次系列ベースで一定
  (週次は系列の見せ方のみ変える)。

メトリクスのキー・ラベル・daily_score 列名の対応表は `trends.py` に `TREND_METRICS` 定数として置き、
エンドポイントとテストで共有する(DRY)。

### フロントエンド

**Today ページ(既存改修)** — 最小変更:
- `MetricTile` / `Sparkline` に「前日比バッジ」(`+5 ↑` / `-3 ↓`)と
  「7日トレンド矢印」(↗ 改善 / → 横ばい / ↘ 低下)を追加。
- `higher_is_better=true` の指標のみ改善=緑/低下=赤で色付け。中立指標(体重・load)は無彩色。

**新規 Trends ビュー** — 専用ページ:
- 日次/週次トグル。
- 各指標を recharts で表示: 日次=折れ線、週次=棒(週平均)。
- 「良い方向」に応じた色付け。
- ナビゲーション(ヘッダーのタブ/リンク)で Today と切替。

### LLM コメント連携

既存の朝6:30 LLM 生成プロンプト (`backend/app/llm/prompts.py` / `client.py`) に
`recent_trends` を渡す。内容は各メトリクスの `direction` と `week_over_week`。
プロンプトに「直近のトレンドに言及する」指示を追加し、
「総合スコアは改善傾向」等のコメントを生成させる。
`trends.py` の計算結果を再利用(二重実装しない)。

## データフロー

1. Garmin同期 → `recompute.py` が `daily_score` 等を更新(既存、変更なし)。
2. `/api/trends` リクエスト時に `trends.py` が DB から系列を読み計算(オンデマンド、キャッシュなし)。
3. フロントが Today / Trends で表示。
4. 朝6:30 の LLM 生成が `trends.py` の結果をプロンプトに含める。

トレンドはオンデマンド計算とし、新テーブル (`trend_summary`) は追加しない(YAGNI、データ量が小さく計算は軽量)。

## エラーハンドリング

- データ不足(系列が2点未満): `direction=null`, `prev_day_change=null` を返し、UIは「計測中(n日)」表示。
- null サブスコア(その日に該当データがない): 系列から除外して計算。既存 `composite.py` の方針に合わせる。

## テスト

- `backend/tests/` に `test_trends.py` を追加:
  - 前日比・前週比の計算
  - 線形回帰による direction 判定(improving/stable/declining)
  - higher_is_better の方向反転(体重等の中立扱い含む)
  - カレンダー週(JST 月曜始め)集計の境界
  - データ不足時の null ハンドリング
- `ruff check` / 既存 pytest が緑であること。

## ビルド・デプロイ

- frontend: `cd frontend && npm run build`
- backend: `.venv/bin/pytest && .venv/bin/ruff check app/ tests/`
- デプロイ: `bin/up.sh`(`op run` で 1Password secrets 解決 → `docker-compose up`)
