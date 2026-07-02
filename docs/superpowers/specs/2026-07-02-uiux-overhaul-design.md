# UI/UX 改革 (4フェーズ一括): 部品基盤 → 記録導線 → IA → 相談ハブ

## 背景 (2026-07-02 俯瞰診断より)

- 60 コンポーネント中 58 が単発 import で見た目・状態表示を各自再発明。32 ファイルがロード中に無言 `return null`(パネルがバラバラにポップインしレイアウトが揺れる)。ErrorState 共通表現なし。
- 生 hex が 16 ファイル・約230箇所(トークン定義はあるのに SVG/チャートが独自パレット)。
- 三層ナビ(下部5 × Today 8タブ × Compass 3タブ)+ 到達不能ページ(Journal/Checkup)。
- 記録 UI(カフェイン/酒/調子/頭痛/介入)がタブ横断で散在し、毎日の入力コストが高い。
- 相談 AI は全データを持つのに、機能側から孤立(導線なし・記録も書けない)。

## Phase 1: 共有プリミティブ + トークン化

- `ui/cockpit.tsx` に追加: `SectionHeader`(Today ローカルから昇格)、`LoadingState`(パネル形状スケルトン、height 指定可)、`ErrorState`(1行メッセージ+再試行)。
- `lib/palette.ts` 新設: tailwind トークンと同値の TS 定数(`P.act`/`P.info`/`P.prog`/`P.risk`/`P.ink`/`P.inkDim`/`P.inkFaint`/`P.hairline`/`P.panel` 等)。SVG/チャートの生 hex はこれを import して置換(Tailwind クラスにできない属性のため)。
- 生 hex 置換マッピング(主要): `#f59e0b`→act, `#fbbf24`→act-300, `#38bdf8`→info, `#34d399`→prog-300, `#10b981`→prog-500, `#ef4444`/`#f87171`→risk, slate系(`#64748b`/`#94a3b8`)→inkFaint/inkDim, (`#1e293b`/`#334155`/`#475569`)→hairline/panel。視覚差は微小(同系色への正規化)。
- 無言 `return null` の置換方針: `isLoading` は `<LoadingState/>`、`isError` は `<ErrorState/>`、データ無しのみ従来どおり null。対象はパネル系コンポーネント(ページ骨格は既存 Skeleton を維持)。

## Phase 2: 記録導線の統一 (QuickLogSheet)

- `BottomNav` 中央に「+」ボタン → `QuickLogSheet`(ボトムシート、背景スクリム、下からスライド)。
- シート内クイック記録(既存 API を再利用、新規エンドポイントなし):
  - カフェイン: プリセットのワンタップ(`api.caffeine*`)
  - 酒: プリセット+数量(`api.alcoholAdd`/presets)
  - いまの調子: 4軸5段ドット(`api.postCheckin`)
  - 頭痛: 開始/強度/終了(`api.migraine*`)
  - 睡眠介入: 4トグル(`api.sleepInterventionSet`)
  - 食事: MealPlanner へのショートカット(#today 健康タブへ遷移。複雑すぎるためシート内には置かない)
- 記録成功で該当クエリ invalidate(既存パネルと同じキー)。既存パネルは分析文脈用に残置。

## Phase 3: IA(ナビ)再編

- 下部ナビ: **今日 / 羅針盤 / ＋ / 資産 / 相談**(「庭」を外し中央を + に)。
- 庭は Compass(羅針盤)の第4タブとして統合(`embedded` パターン、既存 Identity/Life/Becoming と同様)。
- Compass に Journal / Checkup への正式リンク行を追加(到達不能の解消)。
- ハッシュルーティング(`#garden` 等)は互換のため全部残す。Today の8タブは今回触らない。

## Phase 4: 相談 AI ハブ化

- **深リンク**: `#consult?prefill=<urlencoded>` を ConsultChat が初期表示時に入力欄へ流し込む。発火点:
  - WellbeingAlertsBanner「AIに聞く」(アラート内容を prefill)
  - SleepInterventionPanel / SleepDriverPanel(判定結果を prefill)
  - Finance ページ(資産サマリを prefill)
- **記録 tool use**(backend `llm/consult.py`): Anthropic tools を追加し、`stop_reason=="tool_use"` のループ(最大3周)で実行:
  - `record_sleep_intervention(date?, earplugs?, eyemask?, nose_strip?, mouth_tape?)` — 「昨日耳栓つけてた」→即記録
  - `record_caffeine(source, amount?)` / `record_checkin(mood?, energy?, stress?, soreness?)`
  - 実装は既存 API ハンドラと同じ DB 操作を直接呼ぶ(`session_scope`)。実行結果を tool_result で返し、最終テキストに反映。
- system prompt に「記録を頼まれたらツールで実際に記録する」を追記。

## 出荷

フェーズごとに独立コミット。最後に push → CI → fp7-e14 auto-deploy(5分)。
検証: 各フェーズで `npm run build`(tsc)+ backend は pytest/ruff。デプロイ後に本番スモーク
(healthz / QuickLog POST / consult tool use で介入記録が書けること)。

## 非目標

- Today 8タブの再構成・summary のパネル削減(次回)。
- 食事のシート内フル記録。プロンプトレジストリ化。context builder 層(バックエンド抜本は別スペック)。
