# トレンドを Today に常設 + 週次回帰線 + 全体ブラッシュアップ

日付: 2026-06-05
前提: [2026-06-04-trend-ideal-achievement-design.md](2026-06-04-trend-ideal-achievement-design.md) の達成度モデルは維持。
今回は「表示場所」と「週次回帰線」と仕上げの改善。

## 目的

トレンドが別ページ(ボタン遷移)に隠れていて目立たない。Today のトップ付近に常設し、
週次にも回帰トレンドラインを出し、重複表示を整理する。

## 変更

### 1. Today にトレンドを常設(レーダー直後)
Today の並び:
```
アドバイス → 総合スコアレーダー → 【トレンド(日次/週次トグル, 6カード)】→ 栄養 → 今夜プラン → メトリクスタイル
```
- 現 `Trends.tsx` のカード描画を再利用可能な **`TrendsSection` コンポーネント**に抽出。
  日次/週次トグルとデータ取得(`api.trends`)を内包し、戻るボタンは持たない。
- Today はレーダー直後に `<TrendsSection />` を挿入。

### 2. 専用ページと重複表示の廃止
- 専用ページ `Trends.tsx`(TrendsPage)を廃止し `TrendsSection.tsx` に置き換え。
- `App.tsx` の `trends` ビュー分岐と `viewFromHash` の `#trends` を削除。
- Today ヘッダーの「トレンド」リンクを削除。
- Today 下部の **スパークライン4枚を廃止**(生値推移はトレンドカードと重複)。
  それに伴い不要になる `Sparkline.tsx` と `TrendBadge.tsx` を削除し、
  Today の `scoreSeries`/`weightSeries`/`sleepSeries`/`hrvSeries`/`trends` の各 `useQuery` を削除
  (取得は `TrendsSection` 内に移る)。
- 「今の値」一覧の `MetricTile` セクションは役割が異なるため残す。

### 3. 週次にも回帰トレンドライン
- 現状 `/api/trends` は `weekly` のとき `regression=null`。
- 回帰を **表示系列(raw_series)** に対して計算するよう変更し、daily=日次系列、weekly=週平均系列の
  いずれでも回帰線を返す。`dashboard.py` の `_metric` で、`regression` を `_series_out(raw_pairs)` の
  結果(`[{date,value}]`)から `(date, value)` に戻して `trends.linear_regression_endpoints` に渡す。
- frontend は weekly でも `reg` をマージして点線描画する(BarChart に `Line` を重ねる。
  recharts は `ComposedChart` が必要なので、週次は `ComposedChart`(Bar + Line)に変更)。

### 4. 仕上げ
- `TrendsSection` のヘッダに日次/週次トグルとタイトル「トレンド(理想への接近度)」。
- カード見出し: 指標名 / 現在値(`current_raw`+unit) / 達成度 / 改善・横ばい・低下(緑・灰・赤)。
- グリッド: `sm:grid-cols-2 lg:grid-cols-3`。
- 回帰線はオレンジ点線、理想ゾーンは帯(band)または目標ライン(upper)。

## ファイル

- Modify: `backend/app/api/dashboard.py`(regression を表示系列ベースに)
- Modify: `backend/tests/test_dashboard_api.py`(weekly で regression が返ることを検証)
- Create: `frontend/src/components/TrendsSection.tsx`(カード+トグル+取得)
- Delete: `frontend/src/pages/Trends.tsx`, `frontend/src/components/Sparkline.tsx`, `frontend/src/components/TrendBadge.tsx`
- Modify: `frontend/src/pages/Today.tsx`(レーダー直後に TrendsSection、スパークライン/不要 useQuery 削除、リンク削除)
- Modify: `frontend/src/App.tsx`(trends 分岐削除)

## テスト
- backend: `test_trends_endpoint_weekly` を「regression が not null」に更新 + 既存維持。
- frontend: `npm run build`(型・ビルド)。

## ビルド・デプロイ
[[healthcare-deploy-ops]] の通り: backend は `hc-backend-test` イメージで pytest+ruff、
frontend は `npm run build`、デプロイは `! op signin && bin/up-mac.sh`(ユーザー実行)。デプロイ後 PWA リロード2回。
