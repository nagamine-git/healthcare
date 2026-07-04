# ワークアウト一言評価 (タップで LLM 評価 → 永続化)

## 要望 (2026-07-04)

「今日の流れ」のトレーニング (例: 20:59 ランニング16分) に一言評価を付けたい。
LLM を使うなら**タップで評価**(自動生成しない=コスト意識)、**あとから見返せるよう記録**する。

## 設計

- **モデル** `WorkoutReview`: `workout_id`(String PK, workout.id), `text`(400), `tone`(good|caution|info),
  `model`, `created_at`。新テーブルなので create_all で自動作成。
- **LLM** `llm/workout_review.py`: tool_use で `{text(≤160字), tone}` を強制。コンテキストは
  当該 workout (種別/時刻/時間/距離/心拍/TE/HRゾーン/BB増減) + 同種目の直近5回比較 +
  今夜の就寝計画 + 前回筋トレからの日数。データ欠損 (GPS無し等) への言及も指示。
- **API** `api/workout_review.py`:
  - `GET /api/workout-reviews?days=2` → 直近のワークアウト一覧+保存済み評価
  - `POST /api/workout-reviews/{workout_id}` → 未評価なら生成して保存 (`?force=1` で再生成)。
    冪等: 保存済みなら再生成せずそれを返す (LLMコストはタップ時の1回だけ)。
- **UI** `WorkoutReviewStrip.tsx`: DayStory の「今日のハイライト」直下。ワークアウトごとに
  1行 (時刻・種別・時間) + 保存済み評価文 (tone で色分け) or 「AI評価」ボタン。
  自己完結 (独自クエリ) なので DayStory 本体のデータ配線は触らない。

## テスト

API レベル (LLM は monkeypatch): 生成→保存→GET で見える / 2回目 POST は再生成しない /
force=1 で再生成 / 存在しない workout_id は 404。

## 非目標

自動評価 (cron)・評価の編集・古いワークアウトの一括評価。
