# アプリ内「測定モード」機能 設計

作成日: 2026-06-22

## 背景・目的

自宅フィットネスチェック (`docs/superpowers/specs/2026-06-22-home-fitness-test-design.md`) は
測定そのものをユーザー任せにしており、手順テキストに「メトロノームは外部アプリ」「ストップ
ウォッチ別途」と書いて数値を手入力させている。外部ツールへの依存と手作業のカウントは摩擦が
大きく、リズム/タイミングの再現性も落ちる。

そこで、**リズム/時間駆動で測れるテストはアプリ内に測定ツールを内包する**。全画面「測定モード」
で、メトロノーム・タイマー・ハンズフリーのカウントを提供し、終了後に回数を既存の記録入力へ
戻して人が確認・補正してから記録する。

対象テスト (リズム/時間駆動の2種):

- `push_up` — 80bpm メトロノーム + 顎タッチ大ボタンで回数カウント + リズム遅延で自動停止
- `chair_stand` — 30秒カウントダウン + マイクのオンセット検出 (声/物音/足音) でカウント

`grip` (ハード機器必須)・`srt` (目視採点) は対象外。従来どおり手入力。

## 全体方針

- **バックエンドにエンドポイント追加・DB 変更は不要。** 既存 `POST /api/fitness/results` を
  そのまま使う。測定ロジックはフロント完結。
- バックエンドの変更は「どのテストが測定対応か」を宣言する **1 フィールド追加のみ** (ロジックなし)。
- 測定結果は**自動送信しない**。終了時に既存の数値入力欄へ流し込み、ユーザーが確認・±補正して
  から「記録」を押す。マイク/タップ由来の誤カウントを必ず人が訂正できる導線にする。

## アーキテクチャ

### 1. テスト定義に測定モードを宣言 (`backend/app/scoring/fitness_test.py`)

`FitnessTestDef` に 1 フィールド追加:

```python
measure_mode: str | None = None  # "metronome_tap" | "timer_clap" | None
```

- `push_up`: `measure_mode="metronome_tap"`
- `chair_stand`: `measure_mode="timer_clap"`
- `grip` / `srt`: `None` (デフォルト)

`def_payload` で素通し:

```python
"measure_mode": defn.measure_mode,
```

テスト定義をバックエンドのコードに一元化する既存方針 (Learning のカリキュラム定義と同じ) に沿う。
評価・トレンド・due のロジックには一切影響しない。

### 2. 測定フック (`frontend/src/lib/measure.ts` + フック群)

副作用を持つフックと、テスト可能な純粋関数を分離する。

**純粋関数** (`frontend/src/lib/measure.ts`):

- `bpmToInterval(bpm: number): number` — 1 拍の秒数 (60/bpm)。
- `repIntervalSec(bpm: number): number` — 腕立て 1 回 = 2 拍 (下げ/上げ) の秒数。
- `shouldAutoStop(lastTapAt: number, now: number, repInterval: number, beat: number): boolean`
  — 最後のタップから `repInterval + 3*beat` 経過で true (プロトコル「3拍以上遅れたら終了」)。
- `isOnset(level: number, prevLevel: number, threshold: number): boolean`
  — 音量が閾値を下から上に跨いだ瞬間に true (立ち上がりエッジ検出)。

**フック** (`frontend/src/hooks/`):

- `useMetronome(bpm)` — Web Audio API。lookahead スケジューラ
  (`setInterval(25ms)` + `audioContext.currentTime` 先読みで次拍をスケジュール) で
  正確にビープ。`{ start, stop, isRunning, beat }`。iOS Safari 対策でユーザー操作起点に
  `audioContext.resume()`。
- `useWakeLock()` — `navigator.wakeLock.request('screen')`。アンマウント/閉で解放。
  非対応は無害な no-op。
- `useOnsetCounter()` — `getUserMedia({audio})` → `AnalyserNode`。`requestAnimationFrame`
  ループで RMS を取り、`isOnset` + 不応期 (~400ms) で 1 音 1 カウント。
  `{ count, start, stop, reset, adjust, supported, denied }`。拒否/非対応で `denied`。

### 3. 測定モーダル UI (`frontend/src/components/measure/`)

- `MeasureModal.tsx` — 全画面オーバーレイの共通シェル。テスト名・特大カウント表示・
  終了/中止・±補正ボタン・エラーバナー。Wake Lock をここで取得/解放。
  `onFinish(count: number)` で親に確定値を返す。
- `PushUpMeasure.tsx` (`metronome_tap`): `useMetronome(80)` 稼働 (3-2-1 リードイン後カウント開始)。
  特大「顎でタッチ」ボタン、1 タップ = 1 回。`shouldAutoStop` 成立で自動停止。手動「終了」も常時可。
- `ChairStandMeasure.tsx` (`timer_clap`): 30 秒カウントダウン (開始ビープ + 終了ビープ)。
  `useOnsetCounter` のライブカウントを大きく表示、±補正可。0 秒で自動停止。
  マイク拒否/非対応時はタイマーのみ + 手入力フォールバック (バナーで明示)。

### 4. TestCard への統合 (`frontend/src/components/FitnessTestPanel.tsx`)

- `d.measure_mode` があるテストだけ、記録入力行に「測定」ボタンを追加。
- タップで `measure_mode` に応じたモーダルを開く。
- `onFinish(count)` で既存の `value` state に流し込む (自動送信しない)。
- ユーザーが確認・補正 → 既存 `record.mutate` で記録。grip/srt は変更なし。

### 5. 型 (`frontend/src/lib/api.ts`)

`FitnessTestEntry["definition"]` に `measure_mode: "metronome_tap" | "timer_clap" | null` を追加。

## データフロー

```
TestCard「測定」→ MeasureModal 起動 (Wake Lock 取得)
  push_up : メトロノーム80bpm + 顎タッチカウント → 3拍遅延で自動停止
  chair_stand: 30秒タイマー + マイクオンセットカウント → 0秒で自動停止
  → 終了時 onFinish(count) → 既存 value 入力欄へ流し込み (未送信)
  → ユーザー確認・±補正 → 記録ボタン → POST /api/fitness/results (既存)
```

## エラー処理・エッジケース

- **マイク拒否/非対応** (`chair_stand`): タイマーのみ + 手入力に降格。バナーで明示。
- **Wake Lock 非対応**: 無視して機能継続。
- **AudioContext** (iOS Safari): ユーザー操作起点でのみ `resume()`。「測定を始める」タップで実行。
- **腕立ての短いポーズで誤自動停止**: 閾値はプロトコル準拠 (3拍)。再測定で対応。終了後 ±補正可。
- **誤カウント全般**: 自動送信せず、終了後に必ず人が確認・補正してから記録。

## テスト戦略

- フロントにテスト基盤 (vitest 等) が無く、本機能のために新規導入はしない (スコープ外)。
  純粋関数 (`bpmToInterval` / `repIntervalSec` / `shouldAutoStop` / `isOnset`) を副作用ゼロで
  切り出し、`npm run typecheck` + 実機 (PWA) での手動検証で担保する。
- バックエンド (pytest, TDD): `backend/tests/test_fitness_api.py` に
  `push_up`/`chair_stand` の `measure_mode` が API ペイロードに出ること、`grip`/`srt` が
  `None` であることのアサートを追加。

## デプロイ

実装・型チェック・pytest 通過後、既存のデプロイ手順 (memory: deploy-mechanism) に従い
tailscale 環境へデプロイ。DB 変更なし・新規エンドポイントなしのため、フロントビルド +
バックエンド再起動のみ。
