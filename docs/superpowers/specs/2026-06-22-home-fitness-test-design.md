# 自宅フィットネスチェック機能 設計

作成日: 2026-06-22

## 背景・目的

体型管理は身長・体重・体脂肪率に依存しているが、これらは「形」しか見ない。
筋力・筋持久力・バランス・全身機能といった**機能的フィットネス**は測っておらず、
トレーニングメニューの妥当性検証や、加齢に伴う衰えの早期警報ができない。

そこで、**自宅で器具最小限・短時間で実施でき、かつ医学的に予後との相関が裏付けられた**
体力テストを定期的に記録し、評価バンド・トレンド・次回推奨日を返す機能を追加する。

対象ユーザー: 30代後半・健康な男性、Garmin + 体組成計あり、片頭痛持ち、体型改善志向。

## 採用テスト（コア4種）

医学的妥当性調査の結論に基づき、以下4種を採用する。心肺・柔軟性・反応時間・認知は
理由を添えて見送る。

| test_key | テスト | 測る力 | 単位 | 再測定 | エビデンス |
|---|---|---|---|---|---|
| `push_up` | 腕立て伏せ(80bpm最大回数) | 上肢持久力・心血管 | 回 | 月次(4週) | Yang 2019 JAMA Netw Open: >40回で心血管イベント96%減(HR 0.04)。対象=活動的中年男性で本ユーザーに直撃 |
| `grip` | 握力(デジタル握力計・左右ベスト) | 全身筋力 | kg | 月次(4週) | Leong 2015 PURE(n=139,691): 握力5kg低下ごと全死亡HR 1.16。全テスト中エビデンス最強 |
| `chair_stand` | 30秒椅子立ち上がり | 下肢機能 | 回 | 月次(4週) | サルコペニア診断・要介護を予測。器具ゼロ |
| `srt` | 座って立つテスト(SRT, 0-10点) | 柔軟性+筋力+バランス統合 | 点 | 8-12週 | Brito 2012 EJPC: 0-3点群は8-10点群比 死亡5-6倍 |

### 見送り（実装しない）

- **心肺(CRF)**: 予後エビデンスは最強だが、Garmin が VO2max を既に実測。自宅ステップテスト・
  非運動式推定は冗長。UI では既存 VO2max を「心肺フィットネス」として参照表示するに留める。
- **柔軟性(座位体前屈)・反応時間(定規落下)・認知テスト**: 死亡/疾患アウトカムとの前向き相関が
  代理指標止まり、または信頼性が低い(定規落下 simple版 ICC 0.57)。SRT が柔軟性要素を内包する。

### 片頭痛への安全配慮

運動時頭痛(ICHD-3 4.2)の誘因は無酸素・高強度・Valsalva(息こらえ)。採用4種はすべて
submaximal/固定動作で適合する(1RM系・最大シャトルランは不採用)。力む局面で**呼気を合わせる**
よう各テストのUIに併記し、Valsalva を回避する。

## アーキテクチャ

既存パターン(Learning: カリキュラム定義はコード / 進捗はDB)を踏襲する。
テスト定義・基準値・プロトコルはコードに持ち、DB は結果だけを永続化する。

### 1. データモデル (`backend/app/models/health.py` に追加)

```python
class FitnessTestResult(Base):
    """自宅フィットネスチェックの測定結果 (test_key × 実施日で1行、UPSERT)。"""
    __tablename__ = "fitness_test_result"
    __table_args__ = (UniqueConstraint("test_key", "performed_on", name="uq_fitness_test"),)

    id: int  # PK autoincrement
    test_key: str        # push_up | grip | chair_stand | srt
    performed_on: date   # JST日付
    value: float         # 主指標 (回/kg/点)
    detail_json: dict?   # 握力の左右別など補助情報 {"left": 44.0, "right": 47.0}
    note: str?
    created_at: datetime
```

素直な長format。AlcoholIntake / CaffeineIntake と同じ手動入力系の作り。

### 2. テスト定義 + scoring (`backend/app/scoring/fitness_test.py`)

**テスト定義** `FITNESS_TESTS: dict[str, FitnessTestDef]` をコードに保持:
- `label` / `target`(測る力) / `protocol`(手順テキスト) / `equipment` / `est_minutes`
- `unit` / `retest_weeks` / `warmup`(ウォームアップ1試行破棄の注意) / `migraine_note`(安全メモ)
- `mdc`(最小検出変化: push_up=2, grip=6, chair_stand=2.5, srt=1)

**評価ロジック**:
- `evaluate(test_key, value, age, sex) -> {status, band_label, reference}`
  年齢(birth_dateから算出)・性別でバンド判定。
  - push_up: 40回を北極星に 優/良/平均/要改善
  - grip: 日本人30代男性平均47kg基準 ±5kgバンド(計測値は+0.5kg補正の注記)
  - chair_stand: 30代目安28-34回
  - srt: 0-10をリスク帯 (≤3 警報 / 4-7 / 8-10 良)
  - **年齢・性別が未設定なら絶対値のみ返し、評価バンドは出さない**(誤評価を避ける)
- `trend(test_key) -> {delta, is_real_change}`
  前回比を出し、MDC を超えたかで「実変化」/「誤差範囲」を区別。週次ノイズを実力と誤認させない。
- `next_due(test_key) -> {last_on, due_on, is_due}`
  最終実施 + retest_weeks。テストごとに間隔が異なる。

### 3. API (`backend/app/api/fitness.py`)

- `GET /api/fitness/tests` → 全テスト定義 + 各最新結果 + 評価 + トレンド + 次回推奨/due
- `POST /api/fitness/results` → 結果記録 (UPSERT: test_key × performed_on)
- `GET /api/fitness/history/{test_key}` → 履歴 (トレンド描画用)

`main.py` にルータ登録。

### 4. フロントUI (`frontend/src/components/FitnessTestPanel.tsx` + 子カード)

- テスト一覧カード: 各テストのプロトコル手順(畳み表示) → 実施 → 数値入力。
  握力は左右入力 → ベストを value に。
- 結果表示: 評価バンド(優/良/平均/要改善)、前回比 + 「実変化/誤差範囲」ラベル、次回推奨日。
- 各テストに片頭痛安全メモ(呼気を合わせる等)とウォームアップ注意を併記。
- `frontend/src/lib/api.ts` に型と fetch を追加。

### 5. 配置・既存機能との統合

- **physique タブ内**に `FitnessTestPanel` を追加(`BodyLoadCard` の後)。新タブは作らない
  (体型改善と同じ文脈・トレーニング処方に直結、既存のタブ削減方針に沿う)。
- **Today summary**: due があるテストがあるときだけ軽量バナー
  「今月のフィットネスチェック: ○○が測り時」を表示。due が無ければ何も出さない。
- 心肺は新規テストを作らず、既存 Garmin VO2max を「心肺フィットネス」として参照表示。
- physique 処方への弱点反映(弱い部位を筋トレ処方に注入)は将来拡張とし、今回はスコープ外(YAGNI)。

## データフロー

```
ユーザーがテスト実施 → 数値入力(POST /results)
  → scoring が 基準値評価 + 前回比(MDC判定) + 次回推奨日 を算出
  → physiqueタブのパネルに評価/トレンド表示
  → due になったら Today summary にバナー
```

## エラー処理・エッジケース

- 年齢・性別未設定: 絶対値のみ表示、評価バンドは控える。
- 初回測定: 前回比なし(トレンドは null)。
- 同日再測定: UPSERT で上書き(その日のベスト or 最新)。
- 握力で片側のみ入力: 入力された側を value に。

## テスト戦略 (pytest, TDD)

`backend/tests/test_fitness_test.py`:
- 各テストの評価バンド境界値
- MDC を超える/超えないトレンド判定
- next_due の due/not-due 判定(retest_weeks がテストごとに異なること)
- 年齢/性別欠損時に評価バンドを返さないフォールバック
- 握力 detail_json の左右ベスト採用

## デプロイ

実装・テスト通過後、tailscale 環境へデプロイ(既存のデプロイ手順に従う)。
DB はカラム追加のみ(新テーブル)なので既存マイグレーション方針で対応。
