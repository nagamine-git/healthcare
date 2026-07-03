# 「いまコレ」— 全選択肢横断のネクストアクション提示

## 課題

アプリは大量の情報 (アラート/助言/スコア/パネル) を出すが、「結局いま何をすべきか」を
1つに絞らない。Garmin装着・仮眠・水・プロテイン・チェックイン・介入記録・ジャーナル・
資産更新・学習 (Rust等) — サービス内外の選択肢から**最優先の1手**が知りたい (2026-07-03 要望)。

## 解法

決定論的ランキング (LLM不使用 = 瞬時/無料/説明可能)。純関数 `build_candidates(Inputs, now)` が
候補を優先度つきで生成し、最上位1件 + 次点4件を返す。

- `backend/app/scoring/next_action.py` — `Inputs`(横断スナップショット) / `build_candidates`(純関数・
  テスト済) / `_collect`(DB、gather 単位で fail-safe) / `compute_next_action`
- `GET /api/next-action` → `{primary, others, computed_at}`(Today God object に足さない)
- `frontend NextActionCard.tsx` — Today 最上部 (タブより上、アラートの直上) に常時表示。
  5分毎 refetch。タップで深リンク (`#finance`/`#journal`/`#tab-health` 等) or
  `open-quicklog` CustomEvent でクイック記録シートを直接開く。次点はチップで横並び。

## 候補ルールと優先度 (高いほど先)

| key | 条件 | 優先度 |
|---|---|---|
| alert_critical | ウェルビーイングアラート critical | 95 |
| bedtime_prep | 今夜の計画の入浴-15分〜就寝の間 | 85 |
| advice_due | LLM助言の high/critical アクションが時刻±45分 | 82 |
| nap | Body Battery < 25 かつ 11-19時 | 75 |
| stress_break | 直近30分ストレス平均 ≥ 70 | 72 |
| alert_warning | アラート warning | 70 |
| garmin_wear | 心拍サンプル90分途絶 かつ 8-23時 | 68 |
| caffeine_cutoff | 就寝6h前の -30〜+15分 | 58 |
| water | 起床帯 (7-23時) ペース比 -300ml 以上 | 45/55 |
| protein | 15時以降で目標まで 40g 以上不足 | 50 |
| intervention_log | 18時以降で今夜の介入が未記録 | 48 |
| checkin | 10時以降で主観チェックイン未記録 | 45 |
| journal | 20時以降でジャーナル未記録 | 38 |
| money_update | 入出金データが35日超 or 無し | 35 |
| learning | 14-22時の既定フィラー (Rust等の学習25分) | 30 |
| all_clear | 候補ゼロ時のフォールバック | 0 |

時刻はすべて JST (`app_tz`)。「今夜」の介入記録は sleep_intervention の起床日ルールに従う。

## テスト

`tests/test_next_action.py` (純関数・DB不要): critical が常勝 / Garmin未装着は日中のみ /
水分ペースの時間比例 / 就寝準備ウィンドウとカフェインカットオフ / 助言アクションの時刻一致 /
記録衛生→資産→学習の序列 / 静かな午後は学習フィラー。

## 非目標 (YAGNI)

- 完了トラッキング (「やった」ボタン)・スヌーズ。学習ドメインの実データ連動 (静的フィラーで開始)。
- 通知連携 (既存 notification engine への統合は次段)。
