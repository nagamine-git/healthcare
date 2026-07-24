# Implementation Plan: 就寝前ロギング v2（呼吸/瞑想/カフェイン + Apple Health 書き出し）

## Metadata
```yaml
goal: >
  就寝前の行動(呼吸・瞑想・カフェイン)を正確に記録し睡眠への効果を n-of-1 検証する導線を強化する。
  瞑想を介入フラグに追加し呼吸ともども分析対象へ格上げ、カフェインにドリップコーヒーと
  「規定量の何%」共通入力を追加、記録導線を睡眠導入に集約、呼吸/瞑想完了を Apple Health
  (マインドフル時間) にも write-only で書き出す。
scope: >
  含む: (Phase1/web) meditation フラグ + breathing/meditation の分析格上げ、caffeine の
  drip_coffee プリセット + dose_pct 共通%入力、睡眠導入への導線集約(介入セクション + グローバル
  QuickLogSheet)、healthKit web フックの先行仕込み。
  (Phase2/native) Ascend に HealthKit 書き込みブリッジ + 権限 + capability。
  含まない: 呼吸法の秒数の体調連動動的化(現状維持と決定済み)。mindful_minutes(HAE read)を
  真実源化すること(自前DBを真実源に一本化)。既存 SQLite の破壊的マイグレーション。
constraints: >
  - backend にマイグレーション機構は無い。db.py:_apply_lightweight_migrations の expected dict に
    追記する additive な ALTER のみ(既存 SQLite と互換)。
  - clinical/physiological 定数と personal target は config.py に分離して置く(scoring にハードコードしない)。
  - 真実源は自前DB(sleep_intervention_log / caffeine_intake)。Apple Health は write-only 出力先で、
    分析ロジックは自前DB由来のみ参照し mindful_minutes(HAE read) と混同しない。
  - Phase1 は web 完結で `git push origin main` → CI → 5分毎 auto-deploy で反映。
  - Phase2 は別リポジトリ ~/ghq/github.com/nagamine-git/ascend。iOS 再ビルド・再署名が必要。
  - 呼吸法の秒数(slow_6=吸4/吐6, cyclic_sigh)は科学的根拠のある固定値。変更しない。
```

## Context

### Current State
- **睡眠介入フラグ**: `backend/app/api/sleep_intervention.py:25` `_FLAGS = (earplugs, eyemask, nose_strip, mouth_tape, breathing)`。
  モデル `backend/app/models/health.py:453-470` `SleepInterventionLog`、migration は `backend/app/db.py:137`
  `"sleep_intervention_log": [("breathing", "BOOLEAN")]`。
- **n-of-1 分析**: `backend/app/scoring/sleep_interventions.py`。`INTERVENTIONS`(35-40) は earplugs/eyemask/
  nose_strip/mouth_tape の**4つのみ**で breathing を含まない。`_collect()`(51-101, 特に 96-99) も同4フラグしか拾わない。
  → **breathing は現状分析対象外の未活用フラグ**。エンドポイントは `sleep_intervention.py:153-156` `/api/sleep/interventions`。
- **介入 UI**: `frontend/src/components/SleepInterventionCard.tsx:22-28`(今夜トグル ITEMS 4項目) /
  `SleepInterventionHistory.tsx:21-26`(過去バックフィル 4項目) / `SleepInterventionPanel.tsx:153`(分析表示、
  backend の `s.interventions` を map するだけ=backend に追加すれば自動表示)。`breathing` は手動トグルに無く、
  `WindDownCard.tsx:141-149` の完了時 `api.sleepInterventionSet({ breathing: true })` で自動 ON のみ。
- **型**: `frontend/src/lib/api.ts` `SleepInterventionFlags` に `breathing: boolean | null` は追加済み(前セッション)。
- **カフェイン**: マスタ正本 `backend/app/api/caffeine.py` の `Source`(15-18) / `PRESET_METADATA`(20-28) /
  `PRESET_DEFAULTS`(30-48)。mg 算出は `_mg_for()`(58-62) と `create_intake`(87 `mg = body.amount * mg_per_unit`)、
  `patch`(175 同式)。モデル `backend/app/models/health.py:275-291` `CaffeineIntake`(amount/unit/mg/note、dose_pct 無し)。
  入力 body `CaffeineIntakeIn`(caffeine.py:55-60)。presets 配信 `GET /api/caffeine/presets`。
  フロント UI: `CaffeinePanel.tsx`(健康タブ、`PresetRow` 363-417 が量入力+mgプレビュー、対象配列 137-144) /
  `QuickLogSheet.tsx`(グローバル「+」、`PresetGrid` 44-70 ワンタップ既定量)。ラベル重複: `CaffeinePanel.tsx:15-23`
  `SOURCE_LABEL`、`QuickLogSheet.tsx:26-33` `CAFFEINE_LABEL`、型 `api.ts:251-258`、LLM 説明 `llm/consult_tools.py:50-51`。
  薬物動態は config.py:207-226(mg さえ正しければ既存ロジックそのまま流用可)。ドリップコーヒー相当プリセットは**無い**。
- **睡眠導入レイアウト**: `frontend/src/pages/Today.tsx:373-382`。`<WindDownCard />` →「就寝前の介入 × 睡眠の質」
  SectionHeader → `<SleepInterventionCard />` → `<SleepInterventionHistory />` → `<SleepInterventionPanel />`。
- **ネイティブブリッジ**: web 側 `frontend/src/lib/feedback.ts`(haptic)/`wakeLock.ts`(keepAwake) が
  `window.webkit.messageHandlers.<name>` を叩く。native 側 `~/ghq/github.com/nagamine-git/ascend/Ascend/`:
  `WebView.swift`(16-17 で haptic/keepAwake ハンドラ登録、Coordinator switch 33-40)、`HapticBridge.swift`、
  `KeepAwakeBridge.swift`、`Info.plist`(HealthKit 権限記述**無し**)、`Ascend.xcodeproj`(HealthKit capability/
  entitlements **無し**)。**HealthKit 書き込み経路は存在しない**。
- **Apple Health 取り込み**: `backend/app/ingest/hae_parser.py` + `POST /ingest/health-auto-export`
  (`api/health_export.py`) は iPhone→サーバーの**片方向**。逆(サーバー/native→HealthKit)は無い。
  backend は `mindful_minutes`(MetricSample)を `scoring/domains.py:151,253` で**読む**のみ。

### Target State
- 睡眠介入に `meditation` フラグが追加され、`breathing` ともども手動トグル(今夜/過去)と n-of-1 分析に載る。
- カフェインに `drip_coffee` プリセットが加わり、全プリセット(薬含む)で「規定量の何%」(dose_pct)を
  %スライダー+基準mg表示で指定でき、`mg = amount × mg_per_unit × dose_pct/100` で算出・DB に % が残る。
- 睡眠導入の導線: 介入セクションに「呼吸で整える」常設リンク + 瞑想/呼吸のワンタップ記録、
  グローバル QuickLogSheet にも睡眠系(瞑想した/呼吸した)クイック記録が入る。
- 呼吸/瞑想セッション完了時、web が `window.webkit.messageHandlers.healthKit` があれば
  `{type:"mindful", minutes}` を postMessage(未対応環境では無害スキップ)。自前DB記録は従来通り継続。
- Phase2: Ascend が `healthKit` ハンドラ + `HealthKitBridge.swift`(HKCategoryType `.mindfulSession` を save) +
  Info.plist `NSHealthUpdateUsageDescription` + HealthKit capability/entitlements を持ち、mindful session を書く。

### Key Discoveries
- `breathing` は追加済みだが `sleep_interventions.py:35-40 INTERVENTIONS` と `_collect()` に無く**分析されていない**。
  meditation 追加時に breathing も同時に INTERVENTIONS/_collect に入れないと同じ穴に落ちる。
- `SleepInterventionPanel.tsx:153` は backend 追従で自動表示 → 分析側追加だけで表示は済む(UI 変更不要)。
- caffeine の mg エンジンは `create_intake:87` と `patch:175` の**2箇所**の同一式。dose_pct 対応はこの2行 +
  `_mg_for`/`CaffeineIntakeIn` の拡張で足りる。
- ラベルは backend 1 + frontend 3(api.ts 型 / CaffeinePanel / QuickLogSheet) + LLM 1 の計**5箇所**同期が必要。
- Ascend は薄い WKWebView シェル。HealthKit 追加は WebView.swift(ハンドラ登録+switch case) / 新規 Bridge /
  Info.plist / xcodeproj capability の 4 種変更。

---

## Implementation Steps

> Phase 1 = web(healthcare)。Step 1〜7。完了後 `git push` でデプロイ検証 → Phase 2(Ascend) Step 8。

### Step 1: meditation カラム + migration(backend データ層)
**Objective:** sleep_intervention_log に meditation を additive 追加。

**Changes:**
- `backend/app/models/health.py` `SleepInterventionLog`(465 付近、breathing の直後)に
  `meditation: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # 就寝前の瞑想セッション`。
- `backend/app/db.py:137` の `"sleep_intervention_log"` リストへ `("meditation", "BOOLEAN")` を breathing と並べて追記。

**Verify:** `docker compose exec backend python -c "from app.db import ...; create_all()"` 相当 or 起動でエラーなし。
既存 SQLite に対し ALTER が冪等に走ること(既存 breathing 追加と同パターン)。

### Step 2: meditation を API フラグに追加(backend API 層)
**Objective:** POST/GET/history が meditation を受理・返却。

**Changes:**
- `backend/app/api/sleep_intervention.py:25` `_FLAGS` に `"meditation"` 追加。
- `_to_dict`(34-52)・`InterventionIn`(55-64 に `meditation: bool | None = None`)・`get_history`(116-150)の
  レスポンス組み立てに meditation を追加(breathing と同じ扱いを踏襲)。

**Verify:** `POST /api/sleep-intervention {"meditation": true}` → GET で `meditation: true` が返る(pytest or curl)。

### Step 3: breathing + meditation を n-of-1 分析に格上げ(backend scoring 層)
**Objective:** 分析対象に breathing/meditation を追加(breathing の既存の穴も塞ぐ)。

**Changes:**
- `backend/app/scoring/sleep_interventions.py:35-40` `INTERVENTIONS` に
  `("breathing", "呼吸法")`, `("meditation", "瞑想")` を追加。
- `_collect()`(96-99 のフラグ収集)に `breathing`/`meditation` を追加し SleepSession と突合できるように。
- `_EXPLORE_ORDER`(32) に含めるか判断(既存4つと同列に探索対象化 = 含める)。

**Verify:** `backend/tests/` に breathing/meditation を含む介入ログ+睡眠スコアの fixture で
`analyze()` が両者の効果行を返すことを確認する新規ユニットテスト(CLAUDE.md 規約: 新 scoring は必ずテスト)。
`.venv/bin/python -m pytest tests/test_sleep_interventions.py -q`(Docker ワンオフ)。

### Step 4: caffeine dose_pct カラム + drip_coffee プリセット(backend)
**Objective:** ドリップコーヒー追加と % 倍率の永続化・mg 算出。

**Changes:**
- モデル `backend/app/models/health.py` `CaffeineIntake`(275-291)に
  `dose_pct: Mapped[float] = mapped_column(Float, default=100.0)  # 規定量に対する割合(%)`。
- `backend/app/db.py` `_apply_lightweight_migrations` の expected dict に
  `"caffeine_intake": [("dose_pct", "REAL DEFAULT 100")]` を追記(既存 caffeine_intake 行があれば統合)。
- `backend/app/api/caffeine.py`:
  - `Source`(15-18) に `"drip_coffee"` 追加。`PRESET_METADATA`(20-28) に
    `"drip_coffee": {"label": "ドリップ", "emoji": "☕"}`。`PRESET_DEFAULTS`(30-48) に
    `"drip_coffee": {"unit": "杯", "default_amount": 1.0, "mg_per_unit": 100.0}`
    （100mg/杯=規定量。根拠コメント: USDA brewed coffee ~95mg/8oz・日本食品標準成分表 ~90mg/150ml の相場。
    clinical 相当だが飲料マスタなので caffeine.py に集約する既存スタイルに倣う）。
  - `CaffeineIntakeIn`(55-60) に `dose_pct: float = 100.0`(>0 の制約)。
  - mg 算出を `create_intake:87` と `patch:175` の 2 箇所とも
    `mg = body.amount * mg_per_unit * (body.dose_pct / 100.0)` に変更。行の row.dose_pct も保存。
  - `GET /api/caffeine/presets` に各プリセットの `default_mg`(=default_amount×mg_per_unit) を含め、
    フロントが「規定量mg=100%」の基準を表示できるようにする。
  - `llm/consult_tools.py:50-51` の source 説明に drip_coffee を追記(記録ツールが dose_pct を送れるなら併記)。

**Verify:** `POST /api/caffeine {"source":"drip_coffee","amount":1,"dose_pct":150}` → `mg==150`。
`dose_pct` 未指定で 100% 相当(後方互換)。既存レコード読み出しで dose_pct=100 デフォルト。

### Step 5: フロント型 + カフェイン UI(%スライダー共通入力 + drip_coffee)
**Objective:** 全プリセットで % 指定、drip_coffee 表示、5箇所ラベル同期。

**Changes:**
- `frontend/src/lib/api.ts`: `SleepInterventionFlags` に `meditation: boolean | null`。
  `CaffeineSource`(251-258)に `"drip_coffee"`。caffeine 記録の body 型に `dose_pct?: number`。presets 型に `default_mg`。
- `CaffeinePanel.tsx`: `SOURCE_LABEL`(15-23) に drip_coffee。表示配列(137-144)に drip_coffee 追加。
  `PresetRow`(363-417) を「規定量(default_mg)を100%とする % コントロール(25/50/75/100/150/200 のチップ or スライダー)
  + 実効mgプレビュー(=default_mg×%/100)」に変更。送信は `{source, amount: default_amount, dose_pct}`。
  薬(ibuquick/bufferin)含む全プリセット共通コンポーネントにする(manual は mg 直接=dose_pct 100 固定でよい)。
- `QuickLogSheet.tsx`: `CAFFEINE_LABEL`(26-33) に drip_coffee。ワンタップは 100%(既定量)記録のまま。

**Verify:** `npm run build`(tsc -b) green。健康タブで drip_coffee 行に % コントロールが出て、
150% 選択→mgプレビューが規定量×1.5、記録後の履歴 mg が一致。QuickLogSheet に drip が出る。

### Step 6: 睡眠介入 UI に meditation + 呼吸/瞑想の導線集約
**Objective:** 手動トグルに meditation(と breathing)を出し、「呼吸で整える」常設リンク+ワンタップ記録を介入セクションへ。

**Changes:**
- `SleepInterventionCard.tsx:22-28` と `SleepInterventionHistory.tsx:21-26` の `ITEMS` に
  `{ key: "meditation", label: "瞑想", icon: <瞑想アイコン> }` を追加(呼吸を手動トグルにも出すか要判断:
  WindDown 自動 ON と二重になるため、breathing は「今夜つけた/外した」を手で上書きできる意味で追加推奨)。
  アイコンは lucide の `Brain`/`Sparkles` 等から選定(既存 Ear/Eye/Wind/VolumeX と調和する線画)。
- 介入セクション(Today.tsx:373-382 の SleepInterventionCard 付近)に「呼吸で整える」常設リンク
  (WindDownCard の全画面セッション起動)を配置。瞑想/呼吸の「やった」ワンタップ記録を同セクションに集約。
- `SleepInterventionPanel.tsx` は変更不要(backend 追従で meditation/breathing 行が自動表示)。

**Verify:** `npm run build` green。睡眠タブで meditation トグルが出て POST が飛ぶ。分析パネルに
呼吸法/瞑想の効果行が(データがあれば)表示。

### Step 7: healthKit web フック先行仕込み + グローバル QuickLogSheet に睡眠系
**Objective:** Apple Health 書き出しの web 側フックと、グローバル「+」への睡眠系クイック記録。

**Changes:**
- `frontend/src/lib/feedback.ts` に haptic/keepAwake と同型の bridge 取得を追加し、
  `writeMindful(minutes: number)`: `window.webkit.messageHandlers.healthKit?.postMessage({type:"mindful", minutes})`。
  未対応(webkit 無し)なら**何もしない**(無害スキップ)。
- `WindDownCard.tsx:141-149` の完了処理で、自前DB記録(既存)に加え `writeMindful(minutes)` を呼ぶ。
  瞑想セッションを作る場合も同様に完了時 `writeMindful` + `sleepInterventionSet({meditation:true})`。
- `QuickLogSheet.tsx` に睡眠系ワンタップ(「瞑想した」→`sleepInterventionSet({meditation:true})`+`writeMindful`、
  「呼吸した」→`sleepInterventionSet({breathing:true})`+`writeMindful`)を追加。

**Verify:** `npm run build` green。web 単体(ブラウザ)で writeMindful 呼び出しが例外を投げず握りつぶされる。
QuickLogSheet に睡眠系ボタンが出て POST が飛ぶ。

**→ Phase 1 デプロイ検証:** 3ファイル群を commit → `git push origin main`。CI green を確認。
PWA はリロード2回で反映(実機で meditation トグル・drip 記録・呼吸完了記録を通し確認)。

### Step 8 (Phase 2 / Ascend native): HealthKit 書き込みブリッジ
**Objective:** Ascend が healthKit メッセージで mindful session を HealthKit に保存。

**Changes(`~/ghq/github.com/nagamine-git/ascend/Ascend/`):**
- 新規 `HealthKitBridge.swift`: `HKHealthStore` を保持、`HKCategoryType(.mindfulSession)` の書き込み権限を
  要求、`handle(_ body: Any)` で `{type:"mindful", minutes}` を受け `HKCategorySample`(開始=now-minutes, 終了=now)
  を save。権限未許可時は静かに no-op。
- `WebView.swift`: `controller.add(context.coordinator, name: "healthKit")` を 16-17 に追加。
  Coordinator の switch(33-40)に `case "healthKit": HealthKitBridge.handle(message.body)`。
- `Info.plist`: `NSHealthUpdateUsageDescription`(「呼吸/瞑想の実施時間を Apple Health に記録します」)を追加。
- `Ascend.xcodeproj`: HealthKit capability を有効化し `.entitlements`(`com.apple.developer.healthkit`)を追加。

**Verify:** Xcode ビルド成功。実機で呼吸完了→初回に HealthKit 権限ダイアログ→許可後、
ヘルスケアアプリ「マインドフルネス」に分数が記録される。再署名・再配信(memory: iOS 配信は署名7日失効に留意)。

---

## Risks & Open Questions
- **二重カウント**: 呼吸/瞑想を HealthKit に書くと HAE 経由で `mindful_minutes` として読み戻る。
  → 分析(sleep_interventions / domains)は自前DBフラグのみ参照し mindful_minutes と混ぜない(制約に明記)。
  domains.py が mindful_minutes をスコアに使っている箇所があるなら、呼吸/瞑想の二重寄与にならないか要確認。
- **breathing 手動トグルの意味**: WindDown 自動 ON と手動トグルが競合し得る。最後の書き込み優先で許容するか、
  自動 ON は「未設定なら true」に留めるか、Step 6 実装時に挙動を1つ決める(open)。
- **drip_coffee の規定量 mg(100mg/杯)** は相場ベースの初期値。config 上書き(instant_coffee_mg_per_g 同様)を
  将来足すかは今回スコープ外。コメントで根拠を明示。
- **Phase2 の署名/権限**: HealthKit capability 追加で provisioning profile 再生成が要る場合あり。実機配信は
  端末ロック解除・署名有効期限(7日)に留意(memory: efg-dashboard-ios / airgap の iOS 配信知見)。
- **ラベル5箇所同期漏れ**: drip_coffee を backend/api.ts/CaffeinePanel/QuickLogSheet/consult_tools の
  いずれかで落とすと生キー表示になる。Step 4-5 で全同期をチェックリスト化。
