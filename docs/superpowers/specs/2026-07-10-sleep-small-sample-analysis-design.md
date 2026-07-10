# 快眠要因分析の小サンプル化 + 今夜の実験提案

日付: 2026-07-10

## 背景 / 問題

睡眠の質(**深睡眠**・効率・スコア・夜間HRV)に効く要因を本人データで出す基盤は既にある:

- `scoring/sleep_interventions.py` — 4 介入(耳栓/アイマスク/鼻/口テープ)× 質アウトカムを
  並べ替え検定 + BH-FDR。verdict と「今夜の検証」提案(`_suggestion`)まで持つ。
- `scoring/sleep_drivers.py` — ライフスタイル要因(就寝タイミング/規則性/午後カフェイン/飲酒/
  運動/歩数/ストレス/睡眠時間)× 質・翌日アウトカムを同手法で。

**問題**: どちらも `n≥6(介入)/ n≥8(ドライバー)` かつ各群 `≥3` の**ハードゲート未満では
"蓄積中 あと N 夜" しか返さず、何も行動につながらない**。手動ログの介入は特にサンプルが
少なく、「今夜何で寝るべきか(データ取得のため)」が肝心の初期に出ない。

## 決定事項(ユーザー確認済み)

- **対象**: 介入 + ライフスタイル要因の**両方**を小サンプル化する。
- **今夜の提案**: 「探索(explore)+活用(exploit)」を**夜 1 から**動かす。
- **小サンプルの見せ方**: 有意水準未満でも**方向(改善/悪化)+効果量**を暗示する。
  正直に `暫定 (n=…・未確定)` とラベルし、**因果・有意は主張しない**。

## 設計

### B1. 小サンプル「暫定シグナル」(`sleep_interventions.py` / `sleep_drivers.py`)

- ハードゲート未満で `status:"accumulating"` 即 return をやめ、**preliminary を返す**。
- 各群 **≥2** あれば、質アウトカムごとに **観測平均差(効果量)+ 方向 + n** を算出。
  並べ替え検定 p も計算するが、n が旧ゲート未満/各群<3 の場合は tier を `"preliminary"` に
  上書きする(p に関わらず underpowered として扱う)。n が育てば trend/suggestive/strong に自動昇格。
- ドライバーは既存の中央値分割で同様に preliminary を算出(pairs が少数でも ≥2 群で出す)。
- 「睡眠時間 → 質」は自明寄りとして除外する既存ロジックは踏襲(質指標を主軸)。
- レスポンスに `preliminary: [...]`(または既存 outcome に `tier:"preliminary"`)を追加。
  `status` は `analyzed`(ゲート達成)/`preliminary`(未満だが出せる)/`accumulating`(データ皆無)。

### B2. 「今夜何で寝るべきか」= 探索+活用(`sleep_interventions.py`)

`_suggestion` を **night-1 capable** な単一プラン推薦器に拡張(ゲートの外でも計算):

- **活用(exploit)**: verdict=improves もしくは preliminary で明確に良好な介入 → 「今夜も ON」。
- **探索(explore)**: カバレッジが最も偏った/未検証の条件を今夜テスト。
  - 片群 `<3` で反対群 `≥3` → 「今夜は外して(または着けて)検証」。
  - 全項目 None / n=0 → 文献的に堅い介入(耳栓・口テープ)から 1 つ試す。
- **交絡崩し**: 常に同時使用の 2 介入 → 「今夜は片方だけ」(既存ロジック継承)。
- 出力は**単一の明確な 1 手**(text + reason + kind ∈ explore/exploit/deconfound)。
  過負荷を避ける("いまコレ"思想)。本格バンディットは作らない(YAGNI・単純均衡)。

### B3. サーフェシング

- `SleepInterventionPanel` / `SleepDriverPanel` を preliminary 表示対応(`暫定` バッジ・
  方向 ▲/▼ + 効果量 + n)。既存の strong/suggestive 表示はそのまま。
- `scoring/next_action.py` に候補 `sleep_experiment` を追加。就寝前ウィンドウ
  (概ね 20:00〜就寝、既存 `bedtime` 利用)で、B2 の今夜プランがあれば「いまコレ」に出す。
  優先度は bedtime_prep より下・記録衛生より上あたり(適時性重視)。

## テスト(純関数中心・DB 不要)

- `sleep_interventions._analyze_rows`:
  - 各群 2-2 → preliminary が出て tier=preliminary、方向・効果量・n が入る
  - n が育つ(各群≥3, n≥6)と従来 tier に昇格
  - 全 None → accumulating
- 今夜プラン(explore/exploit/deconfound)を状況別に(n=0 / 片群不足 / 実証済み良好 / 交絡)
- `sleep_drivers`: pairs 少数で preliminary が出る / ゲート達成で従来通り
- `next_action`: 就寝前ウィンドウで sleep_experiment が出る/外では出ない

## 非目標 (YAGNI)

- 多腕バンディット等の本格的な逐次実験計画。探索は単純なカバレッジ均衡ヒューリスティック。
- 介入の自動記録。今夜プランは提案のみ(記録は既存 `SleepInterventionCard`)。
