# 主観チェックイン (気分/活力/ストレス/筋肉痛)

日付: 2026-06-09 / 依頼: 「他に管理すべきもの」のメタ検討 → 主観チェックインが最善と判断

## 背景

客観データ (HRV/睡眠/Body Battery 等) は手厚いが、「実際どう感じるか」という**結果変数**が
欠けている。5 秒で入る主観記録を足すと、(1) LLM が体感を踏まえた助言を出せ、(2) 将来
「どの客観要因が良い/悪い日を予測するか」を相関分析できる (頭痛要因分析の並べ替え検定エンジンを
再利用)。本 spec は v1 = 記録 + 表示 + LLM 連携まで。相関分析はデータが溜まってからの後続。

## データモデル

`subjective_checkin` (date 主キー, JST 日付):
- mood: int | None (1-5、高いほど良い)
- energy: int | None (1-5、高いほど良い)
- stress: int | None (1-5、高いほどストレス大 = 悪い)
- soreness: int | None (1-5、高いほど筋肉痛が強い)
- note: str | None
- updated_at: datetime

全項目 optional。1 日 1 行を upsert。

## API (`app/api/checkin.py`)

- `GET /api/checkin?days=14` → `{today: {...}|null, items: [...]}`
- `POST /api/checkin` body `{mood?, energy?, stress?, soreness?, note?, date?}` →
  当日 (or 指定日) を upsert し最新行を返す。各値は 1-5 バリデーション。

## LLM 連携 (`llm/client.py` + `prompts.py`)

- today payload に `subjective`:
  `{today: {mood,energy,stress,soreness}, avg_7d: {...}}`。
- prompt: 「主観 (mood/energy/stress/soreness)。客観スコアと**乖離**があれば一言触れる
  (例: データは良いが本人の活力が低い → 無理させない)。stress/soreness が高い日は負荷を下げる」。

## UI (`CheckinCard.tsx`)

「今日の調子」カード。4 指標それぞれ 5 段階のタップ式 (ドット/絵文字)。タップで即 upsert。
当日値をプリフィル。配置は「いまの状態」付近 (リアルタイムの体感)。
14 日のミニ推移は v1 では省略 (YAGNI、後続)。

## テスト

- API: POST 保存→GET 反映、範囲外 (0 や 6) は 422、部分更新 (mood だけ) で他保持。
- payload: subjective が today payload に入る、7 日平均の算出。

## 非対象 (YAGNI / 後続)
- 客観↔主観の相関分析 (データ蓄積後)。ミニ推移グラフ。ライフドメイン化。
