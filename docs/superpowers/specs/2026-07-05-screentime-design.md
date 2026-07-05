# スマホ依存トラッキング (iOS スクリーンタイム取込)

## 要望 (2026-07-05)

iOS スクリーンタイムのスクショから使用時間を取り込み、スマホ依存を可視化・追跡したい。
複数スクショ (Week 画面 + Day 画面) を一度に取り込みたい。

## 設計 (finance 取込パターンを踏襲)

- **モデル** `ScreenTimeSample`: 複合PK `(period_type, period_start)`。
  `period_type` = day | week。`period_start` = その日 / その週の開始日。
  `daily_min`(1日あたり分: Day=当日合計, Week=日平均 → 横断比較の基準), `total_min`(期間合計・任意),
  `categories`(JSON {name: minutes}), `top_apps`(JSON [{name, minutes}]), `source`, `updated_at`。
- **OCR** `llm/screentime_ocr.py`: tool_use で強制スキーマ
  `{period_type, period_start(ISO), daily_min, total_min, categories, top_apps}`。
  「Yesterday, July 4」「Daily Average」「Last Week's Average」を解釈 (今日の日付をプロンプトに渡す)。
  iOS 週は日曜開始。読めない項目は返さない。複数画像は各々 OCR。
- **API** `api/screentime.py`:
  - `POST /api/screentime/import` (images[]) → 各 OCR → `(period_type, period_start)` で upsert。
  - `GET /api/screentime?days=30` → 直近の day サンプル + 最新 week サンプル +
    集計 (7日平均・エンタメ比率・トレンド方向・時間食いアプリ上位)。
- **集計/依存シグナル** `scoring/screentime.py` の純関数 `summarize(samples)`:
  直近7日の day 平均、前週比、エンタメ (Entertainment) が全体に占める割合、
  上位アプリ、目標 (既定3h/日) 超過フラグ。判定は決定論的 (LLM 不要)。
- **UI** `ScreenTimePanel.tsx`: 健康タブ。日平均・トレンド・カテゴリ内訳バー・上位アプリ・
  「スクショ取込 (複数可)」ボタン。目標超過は赤。既存パネルの配線は触らない。

## テスト

- `summarize` 純関数: 7日平均 / エンタメ比率 / 目標超過 / データ無し。
- API (OCR は monkeypatch): import で day/week 両方 upsert / 同 period 再取込は上書き / GET 集計。

## 非目標

- リアルタイム連携 (iOS はスクショ手動取込のみ)。アプリ個別の制限設定。睡眠との相関分析 (次段)。
- 「いまコレ」への統合 (リアルタイム値が無いため今回は見送り)。
