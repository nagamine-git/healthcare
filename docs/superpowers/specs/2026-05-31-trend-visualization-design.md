# 改善トレンドの可視化 — 設計

日付: 2026-05-31

## 目的

ユーザーが「毎日だんだん数値が良くなっているか」を、日ベース・週ベースで一目で把握できるようにする。
既存の日次スコア (`daily_score`) と各メトリクスは蓄積済みのため、新しい計測ではなく
「既存値の前日比・前週比・トレンド方向」を計算・表示することで実現する。

## スコープ

対象メトリクス: `score`(総合)、`sleep_total_min`、`hrv`、`body_battery`、`weight`、`training_load`。
総合スコアを主役に、各サブ指標も並べて表示する。

非目標(YAGNI): 予測モデル(ARIMA/Prophet)、異常検出アラート、年単位ダッシュボード。

## 用語: 週の定義

- **トレンド方向判定**: ローリング7日(直近7日 vs その前7日)。日々更新され反応が早い。
- **週次グラフ**: カレンダー週(月曜始め, JST)ごとの平均値の系列。週単位の達成感が見える。
- 両者を併用する。

## アーキテクチャ

### バックエンド

**新規 `backend/app/scoring/trends.py`** — 純粋関数群。`daily_score` / 各テーブルから値の日次系列を取り出し、
メトリクスごとに以下を算出する。

- `prev_day_change`: 前日比(絶対値 + 方向)
- `week_over_week`: 直近7日平均 vs その前7日平均(差分 + %)
- `direction`: 直近7日の線形回帰の傾きから `improving` / `stable` / `declining` を判定。
  各メトリクスの「良い方向」を考慮する(体重・training_load の解釈は後述)。
- `weekly_series`: カレンダー週(月曜始め, JST)ごとの平均値の系列

「良い方向(higher_is_better)」のマップ:
- 上昇が改善: `score`, `sleep_total_min`, `hrv`, `body_battery`
- 体重 (`weight`): 中立扱い。方向は出すが改善/低下の色付けはしない(目標体重への接近で評価するのは将来課題)。
- training_load: 中立扱い(ACWR の最適域があり単純な高低で良し悪しを判断できないため)。

`stable` の閾値: 傾きを系列の標準偏差で正規化し、|正規化傾き| が小さい場合は `stable`。

**新規エンドポイント `GET /api/trends`** (`backend/app/api/dashboard.py`):
- クエリ: `?granularity=daily|weekly`(デフォルト daily)、`?days=N`(日次系列の長さ、デフォルト28)
- 返却(メトリクスごと):
  ```json
  {
    "metrics": {
      "score": {
        "label": "総合スコア",
        "current": 78.0,
        "unit": null,
        "higher_is_better": true,
        "prev_day_change": 5.0,
        "week_over_week": { "delta": 3.2, "pct": 4.3 },
        "direction": "improving",
        "series": [{ "date": "2026-05-04", "value": 70.0 }, ...]
      },
      ...
    },
    "granularity": "daily",
    "generated_at": "..."
  }
  ```
- `granularity=weekly` のとき `series` はカレンダー週平均(各点の `date` は週開始日)。

既存 `timeseries()` (dashboard.py) のメトリクス→値抽出クエリを `trends.py` の
共通ヘルパに切り出し、両者で再利用する(重複排除)。

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
