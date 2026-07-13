# MoneyForward 何でもスクショ取込(汎用・重複除去・確度ゲート)

日付: 2026-07-13

## 目的

「様々な MoneyForward スクショを上げる → 中身を読み取り → 重複除去 → **確度が高いものだけ**入れる」。
資産スクショ取込は既存(`extract_assets` + `/import-assets`)。これを **負債・月次収支**まで広げ、
複数画像を横断で dedup し、高確度のみ自動確定・中低確度は「要確認」で保留する。

## 設計(決定論のコアは純関数で TDD)

### OCR (`llm/finance_ocr.py`)
`extract_finance(image_b64)` を新設。画面種別(資産/負債/家計簿=収支)を LLM が判別し返す:
- `assets: [{name, value, confidence: high|medium|low}]`
- `debts: [{name, value, confidence}]`(借入/ローン/カード残高)
- `income_monthly, expense_monthly, flow_confidence`(収支画面がある時)
既存 `extract_assets` は温存(後方互換)。

### 統合 (`scoring/finance_ingest.py` 純関数)
`consolidate_finance_ocr(results) -> {committed, skipped}`:
- **dedup**: assets/debts を正規化 name で統合(最高確度を採用、同確度なら大きい値)。
  収支は各画像の最高確度の非null値を採用。
- **確度ゲート**: `confidence == "high"` のみ `committed` に。medium/low は `skipped`(要確認)へ。
- routing 情報も付す(assets / debts / income / expense)。

### モデル (`models/health.py`, 追加のみ)
`LifeProfile.monthly_expense_jpy`(月支出。収支スクショの支出を保持し advisor が使う)。

### API (`api/finance.py`)
`POST /api/finance/import-screenshots`(複数画像)→ 各画像 OCR → consolidate →
committed を確定(資産=AssetHolding upsert / 負債合計→LifeProfile.debt_balance /
収入・支出→LifeProfile)→ `compute_finance()` + `import_summary{entered, skipped}` を返す。

### アドバイザー (`scoring/finance.py`)
cashflow 無し時のフォールバックを拡張: `avg_income = cashflow or profile.income`、
`avg_expense = cashflow or profile.expense`、`avg_net = cashflow or (income − expense)`。
→ スクショだけで貯蓄率・純資産・レバレッジ診断が回る。

### フロント (`pages/Finance.tsx`)
既存の資産取込を「MoneyForward スクショ(何でも)を取込」に一般化。複数選択 → 送信 →
`entered / skipped(要確認)` の要約を表示(高確度は入った、要確認は手動で、と正直に)。

## テスト
- `consolidate_finance_ocr`: dedup / 確度ゲート(high のみ committed)/ 収支の採用 / 空
- import エンドポイント(`extract_finance` を monkeypatch): 資産+負債+収支が各所へ確定、skipped 返却
- advisor: profile の income/expense フォールバックで avg_net が出る

## 非目標
- 負債の金利 OCR(MF画面に無い→手動/既定)。取引明細の全文取込(CSV が正)。
