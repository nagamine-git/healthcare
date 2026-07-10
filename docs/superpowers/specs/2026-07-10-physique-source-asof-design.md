# 体型分布パネルに「参考にした最終記録の日時」を表示

日付: 2026-07-10

## 背景 / 問題

`DistributionPanel`(母集団での現在地: BMI / 体脂肪率 / FFMI / VO2max)は推定値を出すが、
**その値が「いつの記録」に基づくか**を示していない。体組成は数日〜数週間更新されないこと
があり、VO2max も屋外ランをしないと更新されない。ユーザーは値の**鮮度**を知りたい
(古ければ「測り直す/走る」という行動につながる)。

## 決定事項

- **粒度**: ソース別に 2 つだけ集約する(per-metric ではない)。
  - BMI / 体脂肪率 / FFMI は同一の体組成記録(`WeightSample`)が元 → 1 つ
  - VO2max は別ソース → 1 つ
- **表現**: 「日付 + 経過日数」。例: `7/2 (8日前)`。VO2max 実測は日付粒度しかないため全体を
  日付粒度に統一する(時刻は出さない)。経過は `今日 / 昨日 / N日前`。

## 設計

### バックエンド (`app/api/body_distribution.py`)

レスポンスにトップレベル 2 フィールドを追加(app_tz の `YYYY-MM-DD` 文字列、無ければ `null`):

- `body_comp_as_of`: 最新 `WeightSample.ts` を app_tz に変換した日付
- `vo2max_as_of`: 実測なら最新 `DailySummary.date`、推定フォールバックなら `MetricSample.ts`
  (`vo2max_estimated`)を app_tz 日付にしたもの。VO2max が無ければ `null`

純粋な母集団ロジック(`scoring/population_norms.build_distribution`)は変更しない。
日時取得・付加はエンドポイント層で完結する(層の分離を維持)。UTC naive → app_tz 変換の
小ヘルパを 1 つ置く。

### フロントエンド (`components/DistributionPanel.tsx`, `lib/api.ts`)

- 型 `PhysiqueDistribution` に `body_comp_as_of: string | null` / `vo2max_as_of: string | null`
- パネル冒頭の説明文の直下に、控えめな 1 行を集約表示:
  > 参考記録 — 体組成 **M/D(N日前)**・心肺(VO2max) **M/D(N日前)**
- どちらかが `null` ならその項目を省略。両方 `null` なら行ごと非表示。
- 経過日数は「今日基準の相対」をフロントで算出(単一ユーザー・Asia/Tokyo なのでローカル日付=app_tz)。

## テスト (`tests/test_body_distribution_api.py` 拡張)

- 体組成レコードのみ → `body_comp_as_of` が入り `vo2max_as_of` は null
- VO2max 実測(`DailySummary`)→ `vo2max_as_of` が実測日
- 推定フォールバック(`MetricSample`)→ `vo2max_as_of` が推定日
- 何も無い → 両方 null

## 非目標 (YAGNI)

- per-metric の日時、時刻粒度、古さ警告色(今回は出さない。将来 B の思想と合流可能)
