# 就寝前介入のバックフィル記録（過去の夜を後から入力）

## 目的

「昨日あれ着けてたな」を後から記録できるようにし、分析を6夜待たずに過去データで即開始できる。
[2026-07-02-sleep-interventions-design](2026-07-02-sleep-interventions-design.md) の拡張。

## 方針（ユーザー確定）

- 過去は記憶が曖昧なので **3状態トグル**（未記録→着けた→外した→未記録）で「覚えているものだけ」記録。
  分析は None をその夜×その介入だけ除外するので部分記録で問題ない。
- 対象は **睡眠データ (SleepSession) がある夜のみ**（分析に使える夜だけ出す）。直近14夜。
- 今夜のカード（タップ=使用・残り自動でなし）は変更しない。過去分だけ3状態・部分更新。

## バックエンド

`api/sleep_intervention.py`:

- **POST に `clear: list[str]` を追加**（checkin.py と同型）。指定フィールドを None に戻す。3状態トグルの
  「未記録へ戻す」を実現。POST は既に `date` 指定対応済み。
- POST 後、全フラグ None かつ note 空になったら **空行を削除**（n_nights 水増し防止・既存の方針を踏襲）。
  部分更新なので None のフィールドは据え置き（既存挙動）。
- **新規 `GET /api/sleep-intervention/history?days=14`**: `SleepSession.date < _target_date()` の夜を新しい順に。
  各夜 `{date, display_label, sleep_score, earplugs, eyemask, nose_strip, mouth_tape}`（ログが無ければ各 null）。
  今夜の pending 日はカードが扱うので history からは除外（`< target`）。

## フロントエンド

- `lib/api.ts`: `SleepInterventionSet` に `clear?: string[]` を追加。型 `SleepInterventionHistoryNight` /
  `SleepInterventionHistoryResp {nights}`、メソッド `sleepInterventionHistory`。
- **`SleepInterventionHistory.tsx`**（開閉式「過去の夜を記録」、カード下に配置）:
  各行 = 日付ラベル + 睡眠スコア + 4つの3状態ミニトグル（アイコン: Ear/Eye/Wind/VolumeX）。
  色: 着けた=緑塗り / 外した=グレー枠 / 未記録=淡い破線。タップで None→True→False→None を循環し、
  True/False は `POST {date, [key]:bool}`、None は `POST {date, clear:[key]}`。楽観更新→onSuccess で
  `["sleep-interventions"]`（分析）と `["sleep-intervention-history"]` を invalidate。
- 配置: `Today.tsx` 睡眠タブ、`SleepInterventionCard` と `SleepInterventionPanel` の間。

## テスト

- 既存 `test_sleep_interventions.py` は不変（純関数ロジックは変わらない）。
- 手動 E2E（fp7-e14）: history GET が睡眠夜を返す / 過去日 POST で True→False→clear が反映 /
  clear で空行が消える / 分析 n_nights が過去記録で増える。

## 非目標

- 睡眠データが無い夜の記録（分析不能なので出さない）。範囲14夜より前の編集。
