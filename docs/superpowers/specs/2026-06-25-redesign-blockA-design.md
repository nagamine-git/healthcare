# フル再デザイン Block A:デザイン言語 + コマンドセンター

- 日付: 2026-06-25
- ステータス: 確定(実装着手可)
- 関連: [[becoming-program]](#2 フル再デザインの第1ブロック)
- 人格: founder-cockpit / IA: コマンドセンター / アクセント: セマンティック2色 / ダークベース

## 1. 目的

アプリ全体を「becoming 体験」の founder-cockpit に作り直す第1ブロック。トークン + コア部品 +
コマンドセンターのホームを作り、**既存データを新言語で再提示**してホームを一新する。既存の
詳細ページ(today/garden/identity/becoming)は reachable のまま、Block B/C で順次移行。
バックエンド非変更=低リスク。

## 2. デザイントークン

`tailwind.config.js` の theme.extend と `index.css` の CSS 変数で定義(両者を一致させる)。

- 背景: `bg`#0a0e14 / `surface`#121821 / `raised`#1a2230 / 境界 `line`#243044
- テキスト: `ink`#e6edf3 / `ink-2`#9aa7b8 / `ink-3`#5b6675
- セマンティック: `prog`(emerald #10b981, 階調 300/500/700/900)/ `act`(amber #f59e0b)/
  `risk`(rose #f43f5e)
- 角丸: panel `12px`(rounded-xl 再定義不要、`rounded-lg`=10/`rounded-xl`=12 を採用)
- タイポ: 見出し=システム grotesk スタック、**数値は tabular で大きく**、mono(時刻/メトリクス)。
  type scale: display 28 / h1 20 / h2 16 / body 14 / cap 12 / micro 10
- モーション: 数値カウントアップ・パネル fade-in(150-250ms)、`prefers-reduced-motion` 尊重

## 3. コア部品(`src/components/ui/`)

各 1 責務・プレゼンテーショナル(データは props)。

- `Panel`({title?, action?, children}) — cockpit カード(surface + line + 微発光)
- `Stat`({label, value, delta?, tone?}) — 大数値 + ラベル + Δ
- `Gauge`({value 0-100, label}) — コンディション等の円弧/バー
- `Button`({variant: "primary"|"ghost"|"subtle"}) — primary=amber
- `Pill`({tone}) — タグ/バッジ
- `AppShell`({children}) — safe-area 対応の外枠 + トップバー(日付/同期/設定)
- 既存 `gardenCellStyle` を流用した `SparkGrid`(ミニ草)

## 4. コマンドセンター(`src/pages/CommandCenter.tsx`)

既存フック(`api.today` / `api.becoming` / `api.garden`)を合成。各モジュールから詳細へ drill。

| モジュール | データ源 | drill 先 |
|---|---|---|
| WellbeingAlerts(critical/warning のみ) | today.alerts | — |
| ConditionGauge(total + sub 3) | today.score | `#today` |
| TodaysOneMove(amber CTA + 生成) | becoming one-move | `#becoming` |
| FlywheelStrip(3指標+診断) | becoming.loop_week | `#becoming` |
| NorthStarStrip(ETA+ボトルネック) | becoming.trajectory | `#becoming` |
| GrassStrip(ミニ草+streak) | garden.grid/streak | `#garden` |
| AdviceLine(headline) | today.advice | `#today` |

- 取得失敗/ローディングは各モジュール単位で graceful(片方落ちても他は出す)。

## 5. ルーティング / シェル

- ハッシュ方式維持(YAGNI)。`#`(空)= **CommandCenter**(新ホーム)。
- 既存の詳細 Today を `#today` に移す(`App.tsx` の分岐に追加、現行 TodayPage はそのまま)。
- `#garden` `#identity` `#becoming` `#debug` は現状維持。
- ナビ: CommandCenter 上部/各モジュールから drill。`#today` 等から `#` へ戻る導線。

## 6. 実装範囲(この第1ブロック)

トークン + `ui/` 部品 + CommandCenter ホーム + ルーティング再編のみ。既存48パネルの全面移行は
Block C。よって本ブロックの差分は新規ファイル中心で既存破壊が小さい。

## 7. テスト / 検証

- `npm run build`(tsc)が通る。
- 実機相当のスクショで cockpit ホームの見た目を確認(run スキル)、ユーザーと一緒に微調整。
- バックエンド非変更ゆえ pytest は影響なし(確認のみ)。

## 8. YAGNI / 後続

- ルータライブラリ導入はしない(ハッシュ維持)。
- 既存48パネルの一括再デザインは Block C。
- ライト/ダーク切替はやらない(ダーク固定)。
