# 生活状況プロフィール + 資産の最善手アドバイザー

日付: 2026-07-12

## 背景 / 問題

ユーザーの問い「なんで金増えないんだろう、賃貸だから？」に、アプリが答えられない。
金融基盤(資産配分/リバランス・ROI・キャッシュフロー/ランウェイ)は既にあるが、
(1) 生活状況(世帯・住居・収入・負債・制度枠)の入力欄が無く、(2) 「なぜ増えないか」の
診断と「今の最善手」の提案が無い。

## 目標モデル(ユーザー確定)

看板指標は **総資産 × 純資産**(= gross × (gross − 負債))。純資産だけでなく「借りられる力
(信用)」も価値、という発想を数式化したもの。守るルールは 1 つ:

> **借金は「金利より稼ぐ資産」に使うときだけ良い借金。それ以外は悪い借金。**

会計的裏付け: 総資産=負債+純資産。総資産×純資産 = 純資産² + 負債×純資産 でレバレッジを
評価するが、DuPont(ROE=ROA+(ROA−i)·D/E)より **金利 i を超える運用でなければ純資産を削る**。
よって看板は「良い借金=青 / 悪い借金=赤」で色分けし、不良レバレッジを罰する。

## 設計(決定論・説明可能。next_action / wellbeing_alerts と同じ流儀。LLM は使わない)

### データモデル (`models/health.py`) — 追加のみ (create_all で互換)

`LifeProfile`(単一行 id=1、UserProfile/FinanceState と同型):
- 世帯: `partner: bool`, `children: int`, `dependents: int`
- 住居: `housing: str` ("rent"|"own"), `housing_cost_jpy: float`(月の家賃 or ローン返済)
- 収入: `monthly_income_jpy: float`(手取り月収の上書き/補完), `income_type: str`
  ("employee"|"self_employed"|"mixed")
- 負債: `debt_balance_jpy: float`, `debt_rate_pct: float`(加重平均金利)
- 制度枠: `nisa_monthly_jpy: float`, `ideco_monthly_jpy: float`
- `note`, `updated_at`

すべて NULL 可(未入力は診断で「不明」として素直に扱う)。

### 閾値 (`config.py`, personal)

- `finance_good_debt_max_rate = 3.0`(%以下=低利・良い借金候補)
- `finance_bad_debt_min_rate = 7.0`(%以上=高利・悪い借金)
- `finance_min_savings_rate = 0.15`(貯蓄率の下限目安)
- `finance_housing_burden_ratio = 0.30`(住居費/収入 の重い閾値)

### アドバイザー (`scoring/finance_advisor.py`)

`build_advisor(...)` を **DB 非依存の純関数**にし、`compute_advisor(session)` が既存の
`compute_rebalance` / `compute_cashflow` と `LifeProfile` から値を集めて呼ぶ。

**看板**: `gross`(=AssetHolding 合計), `debt`, `net = gross − debt`,
`headline = gross × net`。`leverage`: debt=0→"none" / 低利→"good"(青) / 高利→"bad"(赤) /
中間→"caution"(黄)。

**診断 (なんで増えない)** — 各 {key, level(info/warn), text, metric}:
- `savings_rate`: 純額/収入(cashflow 優先)。< 閾値 → 「貯蓄率 X%(主因)」
- `cash_drag`: `rebalance.unallocated`(防衛資金超の未投資現金)> 0 → 「余剰現金 Y が投資されず眠っている」
- `housing_burden`: housing_cost/収入 > 0.30 → 「住居費が収入の Z%」
- `bad_debt`: debt_rate ≥ bad_rate → 「高利の借金(rate%)が純資産を毎年削る」
- `reserve_gap`: reserve < suggested_reserve → 「生活防衛資金が不足」

**最善手 (優先順位つき複数)** — {priority, text, why, kind}、priority 降順:
1. 悪い借金の返済(確実に金利分のリターン)
2. 生活防衛資金の確保(不足時)
3. 現金ドラッグの解消 → NISA/インデックス
4. NISA/iDeCo 枠を使い切る(非課税)
5. 固定費(特に住居費)を見直し貯蓄率を上げる
6. (悪い借金が無く安定収入なら)信用枠=借りられる力を維持(低利ローンは繰上げ返済を急がない)

**リスクの節度**: 「もっと借りろ」とは能動的に言わない(6 は信用維持の助言に留める)。
賃貸 vs 購入は将来の別機能(価格/家賃比・居住年数)として本 spec の非目標。

### API (`api/finance.py`)

- `GET /api/finance/profile` / `PUT /api/finance/profile`(LifeProfile CRUD、config PUT と同型)
- `compute_finance` の返り値に `advisor`(看板+診断+最善手)と `profile` を追加

### フロント (`pages/Finance.tsx`, `lib/api.ts`)

- **生活状況入力フォーム**(詳細): 世帯/住居/収入/負債/制度枠。保存で PUT。
- **看板**: 総資産 × 純資産(良い借金=青/悪い借金=赤)+ gross/net を併記
- **診断**: 「なんで増えない」を数行(貯蓄率・現金ドラッグ・住居費・良い/悪い借金)
- **最善手**: 優先順位つきリスト(text + why)

## テスト(純関数中心)

- `build_advisor`: 看板計算、leverage 良い/悪い/中間、各診断の発火/非発火、最善手の優先順
  (悪い借金 > 防衛資金 > 現金ドラッグ > 制度枠 > 貯蓄率 > 信用維持)、データ欠損時の素直な劣化
- API: profile GET/PUT ラウンドトリップ、compute_finance に advisor が載る

## 非目標 (YAGNI)

- LLM ナラティブ(決定論で十分・説明可能)。賃貸 vs 購入の定量判定。複数負債の個別管理。
