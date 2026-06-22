# アプリ内「測定モード」 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 自宅フィットネスチェックの腕立て・椅子立ち上がりに、メトロノーム/タイマー/ハンズフリーカウントを内包した全画面「測定モード」を追加する。

**Architecture:** バックエンドはテスト定義に `measure_mode` を1フィールド足すだけ (ロジック・DB・エンドポイント変更なし)。測定はフロント完結。純粋関数 (測定判定) + 副作用フック (Web Audio/Wake Lock/マイク) + 全画面モーダルに分離し、終了時に回数を既存の記録入力へ流し込む (自動送信しない)。

**Tech Stack:** FastAPI / pytest (backend), React 18 + TypeScript + Vite PWA + TanStack Query + Tailwind + lucide-react (frontend), Web Audio API / Screen Wake Lock API / getUserMedia (ブラウザ標準, 追加依存なし)。

## Global Constraints

- 追加 npm 依存は入れない (ブラウザ標準 API のみ)。
- 測定結果は自動送信しない。終了時に既存 `value` 入力へ流し込み、ユーザー確認・補正後に既存 mutation で記録。
- バックエンドの評価/トレンド/due ロジックは一切変更しない。
- 設計: `docs/superpowers/specs/2026-06-22-fitness-in-app-measurement-design.md`

---

### Task 1: バックエンドに measure_mode を追加

**Files:**
- Modify: `backend/app/scoring/fitness_test.py` (FitnessTestDef + push_up/chair_stand 定義 + def_payload)
- Test: `backend/tests/test_fitness_api.py`

**Interfaces:**
- Produces: API `/api/fitness/tests` の各 `definition` に `measure_mode: "metronome_tap" | "timer_clap" | null`。

- [ ] **Step 1: 失敗するテストを書く** (`backend/tests/test_fitness_api.py` に追記)

```python
def test_measure_mode_exposed(app_client):
    data = app_client.get("/api/fitness/tests").json()
    modes = {t["definition"]["key"]: t["definition"]["measure_mode"] for t in data["tests"]}
    assert modes["push_up"] == "metronome_tap"
    assert modes["chair_stand"] == "timer_clap"
    assert modes["grip"] is None
    assert modes["srt"] is None
```

- [ ] **Step 2: 失敗確認** — `cd backend && uv run pytest tests/test_fitness_api.py::test_measure_mode_exposed -v` → FAIL (KeyError: 'measure_mode')

- [ ] **Step 3: 実装** — `FitnessTestDef` に `measure_mode: str | None = None` を `has_lr` の隣に追加。`push_up` 定義に `measure_mode="metronome_tap"`、`chair_stand` 定義に `measure_mode="timer_clap"` を追加。`def_payload` の返り dict に `"measure_mode": defn.measure_mode,` を追加。

- [ ] **Step 4: パス確認** — `cd backend && uv run pytest tests/test_fitness_api.py -v` → PASS

- [ ] **Step 5: コミット** — `git add backend/app/scoring/fitness_test.py backend/tests/test_fitness_api.py && git commit`

---

### Task 2: フロント純粋関数 (measure.ts)

**Files:**
- Create: `frontend/src/lib/measure.ts`

**Interfaces:**
- Produces: `bpmToInterval(bpm)`, `repIntervalSec(bpm)`, `shouldAutoStop(lastTapAt, now, repInterval, beat)`, `isOnset(level, prevLevel, threshold)`。

- [ ] **Step 1: 実装** (テスト基盤が無いため typecheck で担保)

```typescript
/** 測定モードの純粋ロジック (副作用なし)。フックから利用し、単体で検証可能に保つ。 */

/** 1拍の秒数。 */
export function bpmToInterval(bpm: number): number {
  return 60 / bpm;
}

/** 腕立て1回 = 2拍 (下げ/上げ) の秒数。 */
export function repIntervalSec(bpm: number): number {
  return bpmToInterval(bpm) * 2;
}

/**
 * 最後のタップから「1回分 + 3拍」経過したら自動停止 (プロトコル「3拍以上遅れたら終了」)。
 * 時刻は performance.now() ベースのミリ秒、repInterval/beat は秒。
 */
export function shouldAutoStop(
  lastTapAt: number,
  now: number,
  repInterval: number,
  beat: number,
): boolean {
  return (now - lastTapAt) / 1000 > repInterval + 3 * beat;
}

/** 音量が閾値を下から上に跨いだ瞬間 (立ち上がりエッジ) を検出。 */
export function isOnset(level: number, prevLevel: number, threshold: number): boolean {
  return prevLevel < threshold && level >= threshold;
}
```

- [ ] **Step 2: typecheck** — `cd frontend && npm run typecheck` → エラーなし
- [ ] **Step 3: コミット** — `git add frontend/src/lib/measure.ts && git commit`

---

### Task 3: 副作用フック (useMetronome / useWakeLock / useOnsetCounter)

**Files:**
- Create: `frontend/src/hooks/useMetronome.ts`
- Create: `frontend/src/hooks/useWakeLock.ts`
- Create: `frontend/src/hooks/useOnsetCounter.ts`

**Interfaces:**
- Consumes: `measure.ts` の `bpmToInterval`, `isOnset`。
- Produces:
  - `useMetronome(bpm): { start(): Promise<void>, stop(): void, isRunning: boolean, beat: number }`
  - `useWakeLock(): { request(): Promise<void>, release(): void }`
  - `useOnsetCounter(): { count, start(): Promise<void>, stop(): void, adjust(d: number): void, reset(): void, supported: boolean, denied: boolean }`

- [ ] **Step 1: useMetronome 実装** — lookahead スケジューラ。`AudioContext` をユーザー操作起点で生成/resume。`start` で 25ms ごとに先読みし、`currentTime + 0.1s` 以内の拍に短いオシレータビープ (1000Hz, 0.05s) をスケジュール。`beat` を加算し state 更新。`stop` で `oscillator`/`interval` を停止。アンマウントで `ctx.close()`。

- [ ] **Step 2: useWakeLock 実装** — `request` で `navigator.wakeLock?.request("screen")` を try/catch。`release` で保持中の sentinel を release。非対応時は no-op。

- [ ] **Step 3: useOnsetCounter 実装** — `start` で `getUserMedia({audio:true})` → `AudioContext` + `AnalyserNode`。`requestAnimationFrame` で RMS を計算し、`isOnset` + 不応期 (前回カウントから 400ms 以上) で `count++`。権限拒否/非対応で `denied`/`supported=false`。`stop` で track/raf/ctx を片付け。`adjust(d)`/`reset()` で手動補正。

```typescript
// useOnsetCounter.ts の検出ループ中核 (抜粋イメージ)
const buf = new Float32Array(analyser.fftSize);
let prev = 0;
let lastCountAt = 0;
const tick = (t: number) => {
  analyser.getFloatTimeDomainData(buf);
  let sum = 0;
  for (const v of buf) sum += v * v;
  const rms = Math.sqrt(sum / buf.length);
  if (isOnset(rms, prev, THRESHOLD) && t - lastCountAt > 400) {
    lastCountAt = t;
    setCount((c) => c + 1);
  }
  prev = rms;
  raf = requestAnimationFrame(tick);
};
```

- [ ] **Step 4: typecheck** — `cd frontend && npm run typecheck` → エラーなし
- [ ] **Step 5: コミット** — `git add frontend/src/hooks && git commit`

---

### Task 4: 測定モーダル (MeasureModal / PushUpMeasure / ChairStandMeasure)

**Files:**
- Create: `frontend/src/components/measure/MeasureModal.tsx`
- Create: `frontend/src/components/measure/PushUpMeasure.tsx`
- Create: `frontend/src/components/measure/ChairStandMeasure.tsx`

**Interfaces:**
- Consumes: Task 3 フック, `measure.ts` の `shouldAutoStop`/`repIntervalSec`/`bpmToInterval`。
- Produces: `MeasureModal({ mode, label, onFinish, onClose })` — `mode: "metronome_tap" | "timer_clap"`。`onFinish(count: number)` で確定値を親へ。

- [ ] **Step 1: MeasureModal 実装** — 全画面 `fixed inset-0 z-50` オーバーレイ。Wake Lock を `useEffect` で取得/解放。`mode` で `PushUpMeasure`/`ChairStandMeasure` を出し分け。特大カウント・終了・中止・±補正・エラーバナーの共通チャイルドを提供。
- [ ] **Step 2: PushUpMeasure 実装** — マウントで `useMetronome(80)` を 3-2-1 リードイン後 start。特大「顎でタッチ」ボタン (`onPointerDown` でカウント+`lastTapAt` 更新)。`requestAnimationFrame` で `shouldAutoStop` を監視し成立で `onFinish(count)`。手動「終了」も `onFinish(count)`。
- [ ] **Step 3: ChairStandMeasure 実装** — マウントで 30 秒カウントダウン (開始/終了ビープは `useMetronome` の単発 or AudioContext)。`useOnsetCounter` のライブ count を大表示、±補正。0 秒で `onFinish(count)`。`denied` なら「マイク不可: 自分で数えて手入力してね」バナー + タイマーのみ。
- [ ] **Step 4: typecheck** — `cd frontend && npm run typecheck` → エラーなし
- [ ] **Step 5: コミット** — `git add frontend/src/components/measure && git commit`

---

### Task 5: api.ts 型 + TestCard 統合

**Files:**
- Modify: `frontend/src/lib/api.ts:1058-1072` (FitnessTestDef に measure_mode)
- Modify: `frontend/src/components/FitnessTestPanel.tsx` (測定ボタン + モーダル起動 + value 流し込み)

**Interfaces:**
- Consumes: Task 4 `MeasureModal`, Task 1 `definition.measure_mode`。

- [ ] **Step 1: 型追加** — `FitnessTestDef` に `measure_mode: "metronome_tap" | "timer_clap" | null;` を追加。

- [ ] **Step 2: TestCard 統合** — `TestCard` 内で `d.measure_mode` があるとき、記録入力行に「測定」ボタンを追加。`useState` でモーダル開閉。`MeasureModal` を `d.measure_mode` で起動し、`onFinish(count)` で `setValue(String(count))` (has_lr テストは対象外なので value のみ)。`onClose` で閉じる。

```tsx
// TestCard 抜粋: 記録ボタンの左に測定ボタン
{d.measure_mode && (
  <button type="button" onClick={() => setMeasuring(true)}
    className="shrink-0 rounded-lg bg-slate-800 px-3 py-1.5 text-xs text-sky-300 hover:bg-slate-700">
    測定
  </button>
)}
...
{measuring && d.measure_mode && (
  <MeasureModal mode={d.measure_mode} label={d.label}
    onFinish={(n) => { setValue(String(n)); setMeasuring(false); }}
    onClose={() => setMeasuring(false)} />
)}
```

- [ ] **Step 3: typecheck + build** — `cd frontend && npm run typecheck && npm run build` → 成功
- [ ] **Step 4: コミット** — `git add frontend/src/lib/api.ts frontend/src/components/FitnessTestPanel.tsx && git commit`

---

### Task 6: 検証 + デプロイ

- [ ] **Step 1: バックエンド全テスト** — `cd backend && uv run pytest -q` → PASS
- [ ] **Step 2: フロント** — `cd frontend && npm run typecheck && npm run build` → 成功
- [ ] **Step 3: デプロイ** — memory `deploy-mechanism` の手順に従う (フロントビルド + バックエンド再起動。DB 変更・新エンドポイントなし)。
- [ ] **Step 4: 動作確認** — 測定モードが腕立て/椅子で開き、回数が入力欄へ戻ることを確認。

## Self-Review

- **Spec coverage:** measure_mode 宣言 (T1) / 純粋関数 (T2) / フック3種 (T3) / モーダル3種 (T4) / 型+統合 (T5) / 検証+デプロイ (T6) — spec の各節を網羅。
- **Placeholder scan:** 各ステップに実コード/実コマンドあり。
- **Type consistency:** `measure_mode` の literal union がバック (T1)・型 (T5)・モーダル props (T4) で一致。`onFinish(count: number)` が T4/T5 で一致。
