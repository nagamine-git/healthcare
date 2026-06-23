# 理解度チェックの回答形式選択 + 得点制クリア

## 背景 / 目的
現状の理解度チェック (`backend/app/llm/quiz.py`) はフリーワード会話のみで、Claude が 0–100% を採点し
80% で章クリア (= 全節「説明できた」)。得点の概念はなく合否のみ。

回答形式 (フリーワード / 4択 / 2択) を**問題ごとに選べる**ようにし、難しい形式ほど高得点とする。
得点を積んで章をクリアする方式に変え、易しい形式だけで逃げ切れないよう品質フロアを設ける。

## 採点スキーム (章ごと)
- クリア閾値: **100 点**。かつ **フリーワード正解 (理解度 ≥ 80%) を最低 1 問**。
- 配点:
  - フリーワード: 理解度 ≥ 80% → **+50**、56–79% → +15、それ未満 → 0
  - 4択: 正解 → **+20**、不正解 → 0
  - 2択: 正解 → **+10**、不正解 → 0
- 不正解にペナルティなし (0 点)。
- クリア条件: `quiz_points >= 100 AND free_word_passed_at is not None`。達成で `mark_chapter_explained`。

到達例: フリーワード2問 / フリーワード1+4択3 / 選択式だけはフリーワード正解が無い限り不可。

## データモデル
`LearningChapterProgress` に追加 (lightweight migration で列追加):
- `quiz_points: int`  累計得点 (None は 0 とみなす)
- `free_word_passed_at: datetime | None`  フリーワード正解した時刻 (品質フロア判定)

クリア後も `quiz_points` は保持 (表示用)。再受験 (review) は採点なし。

## バックエンド
`app/llm/quiz.py`:
- 既存 `quiz_turn` (フリーワード) は維持しつつ、戻り値の理解度から得点付与は API 層で行う。
- 新ツール `generate_choice_question` を追加し `choice_question(chapter, messages, n)` を実装。
  返り値 `{question, options: [str]*n, correct_index, explanation}`。n=4 or 2。

`app/scoring/learning.py`:
- 定数 `QUIZ_TARGET=100, FW_FULL=50, FW_PARTIAL=15, FW_FULL_MIN=80, FW_PARTIAL_MIN=56, CHOICE4=20, CHOICE2=10`。
- `award_quiz_points(chapter, *, free_understanding=None, choice_correct=None, fmt=None) -> dict`:
  得点加算・`free_word_passed_at` 更新・クリア判定。クリアなら `mark_chapter_explained` を呼ぶ。
  返り値に `quiz_points / target / free_word_passed / cleared / state(クリア時)`。

`app/api/learning.py` の `QuizIn` を拡張:
- `format: "free" | "choice4" | "choice2" = "free"`
- `action: "question" | "answer" = "answer"` (choice 用。free は従来どおり answer 相当)
- `selected_index: int | None`、`correct_index: int | None` (choice の採点用に client がエコー)

挙動:
- free: 既存 `quiz_turn` で採点 → `award_quiz_points(free_understanding=understanding)` → 得点・クリアを併合して返す。
- choice + action=question: `choice_question` を生成し `{question, options, correct_index, explanation, format}` を返す (採点なし)。
- choice + action=answer: `correct = selected_index == correct_index` → `award_quiz_points(choice_correct=correct, fmt=...)` → 得点・正誤・クリアを返す。
- review: 既存 `tutor_turn` (不変)。
- LLM 接続失敗は従来どおり穏便な error 応答。

## フロント (`ChapterQuiz.tsx`, `lib/api.ts`)
- 入力域上部に形式トグル: フリーワード / 4択 / 2択。
- フリーワード = 既存の記述 + 理解度ゲージ。選択式 = 「次の問題」で生成 → 選択肢タップ → 正誤と解説を即表示。
- ヘッダの理解度ゲージを **得点進捗バー (◯/100)** に拡張 (フリーワード時は直近理解度%も小さく表示)。
- 選択式の正誤判定はクライアント側 (単一ユーザーの誠実性前提)。フリーワード採点はサーバ側。
- クリア時は従来の演出 + 復習モードへ。

## テスト
- `learning.award_quiz_points`: 加点・閾値・フロア (選択式のみでは未クリア)・クリア時 explained 付与。
- `quiz.choice_question`: ツール応答のパース、n の検証。
- API: free/choice の各 action、cleared 判定、unknown chapter 404。
- フロント: `tsc` ビルドが通ること。

## 非目標 (YAGNI)
- 章ごとに閾値を変える / 難易度別カリキュラム調整。
- 選択式のサーバ側秘匿 (single-user のため client grading で十分)。
- リーダーボード等の独立 XP。
