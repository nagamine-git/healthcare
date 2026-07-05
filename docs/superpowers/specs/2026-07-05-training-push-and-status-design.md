# 鶏卵修正 + トレーニング状況ストリップ

## 背景 (2026-07-05, 本人データで検証)

- BB は朝 61〜82 (満タン) → 夜 12〜24 に自然低下 (誰でも)。**枯渇していない**。
- 「いまコレ」の training_gap ガードが **今この瞬間の BB (`bb_current`)** を見ていたため、
  夜にアプリを見ると毎回「BB低い→休め」。**鶏卵の正体は生理でなくロジックの誤認**。
- 直近21日の筋トレ4回 (6/30,6/28,6/23,6/20)。筋肥大目標 (FFMI 9%ile) には週3〜4回=21日10〜12回
  必要 → **明確に under-training**。アプリは「休め」を連発する言い訳製造機になっていた。

## ① 鶏卵修正 (next_action.py)

training_gap ルールを書き換え:

- **可否判定を「今のBB」→「朝のBB / レディネス」に変更**。朝BB (`BodyBatteryDaily.morning_value`,
  6時固定スナップ) は日中安定で回復状態を正しく表す。夜の自然低下では抑制しない。
- **under-training バイアス**: 直近14日の筋トレ回数を数え、週3回 (=14日6回) 未満なら
  優先度を底上げし、夜でも背中を押す。
- 発火条件: `not trained_today` かつ `days_since_strength >= 2` かつ 8〜21時 かつ
  `morning_bb is None or morning_bb >= 30` (本当に低回復の朝だけ休む)。
- 優先度: under-training なら 66 (days_since で +、5日以上70)。足りていれば 56。
- メニューは朝BB連動: `morning_bb >= 60` → 筋トレ/HIIT/ラッキング、そうでなければ 筋トレ/軽め。
  夜遅く (bedtime 3h 前以降) は「短時間でも」と添える。
- why 文に「今週N回 / 目標3回」を出し **under-training を可視化**。
- `bb_current` は仮眠ルール (nap: 今のエネルギー枯渇) に限定して残す。就寝直前の抑制は
  既存 bedtime_prep / 就寝3時間前ルールが担当 (BB では判定しない)。

Inputs 追加: `morning_bb`, `strength_days_14`。`_collect` で
`BodyBatteryDaily.morning_value`(target 日) と 14日の strength 系 Workout 件数を供給。

## ② トレーニング状況ストリップ (これまで→今→これから)

トレーニング情報が いまコレ / ハイライト / 部位別 / 今夜の計画 / トレンド に散在 → 1本化。

- **API** `GET /api/training-status` (`scoring/training_status.py`):
  - これまで: 今週 (直近7日) の筋トレ回数・有酸素回数、目標3回に対する達成、14日筋トレ回数。
  - 今: `bodyload.state()` の部位別回復サマリ (回復済み/回復途中/直近負荷の数)、
    「今週足りてる?」判定 (`enough` / `behind` / `way_behind`)。
  - これから: 今日やるべき部位 (bodyload.suggestion) + 週目標まで「あとN回」。
- **UI** `TrainingStatusStrip.tsx`: 体型タブ最上部。3カラム (これまで|今|これから) 横並び。
  週回数が目標未満なら赤系で「不足」。回復済み部位を「今日やれる」として提示。
  under-training 時は「積極的に刺激を」の一言。既存 bodyload/DistributionPanel の配線は触らない。

## テスト

- next_action: 朝BB高・夜遅くでも under-training なら training_gap が出る / 朝BB<30 の低回復日は
  出ない / 週3回達成済みなら優先度が下がる / trained_today は抑制 (既存踏襲)。
- training_status: 純関数 `build_status(sessions, groups, now)` で週回数集計・判定・あと何回を検証。

## 非目標

- 部位別ステータスカード自体の再設計 (今回は上に要約ストリップを足すだけ)。ACWR 連動の
  オーバートレ検知の精緻化 (頻度ベースで十分)。トレ種目の自動生成。
