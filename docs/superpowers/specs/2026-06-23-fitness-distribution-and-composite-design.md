# 体力テストの分布可視化 + 総合体力スコア 設計

作成日: 2026-06-23

## 背景・目的
体型(BMI/体脂肪率/FFMI/VO2max)は母集団 percentile で「現在地」を出せるようになった。
同じことを**体力テスト(腕立て/握力/椅子立ち上がり/SRT)**にも適用し、
**個別の分布(同年代・同性 percentile + 釣鐘)**と、医学エビデンスで重み付けした
**総合体力スコア(0-100)**を可視化する。

## 確度(正直に明示)
- **握力**: 母集団データが比較的堅い(国民体力調査ベース)。
- **腕立て・椅子立ち上がり**: 年代別 mean/SD は文献の目安。
- **SRT**: 0-10 の段階評価で釣鐘分布に不向き → 個別は現行バンド表示のまま。
  総合点には 0-10→percentile 換算で算入する。

## 設計判断(確定済み)
- 総合点 = **医学エビデンスで重み付けした個別 percentile の加重平均**。
- SRT = 個別はバンド、総合には換算して含める。

## アーキテクチャ

### 1. percentile 共通化 (`backend/app/scoring/population_norms.py`)
正規分布 percentile の中核を切り出して再利用可能に:
```python
def pct_from(value, mean, sd) -> float | None:  # Φ((v-μ)/σ)*100、0-100クランプ
```
既存 `percentile()` はこれを使うよう内部リファクタ(挙動不変)。

### 2. 体力テストの基準値・percentile・総合 (`backend/app/scoring/fitness_test.py`)
```python
# 連続値テストの母集団 mean/sd (sex × 年代帯)。握力=堅い、他=目安。
FITNESS_NORMS: dict[str, dict[str, list[tuple[int,int,float,float]]]] = {
    "grip": {"male":[(18,29,47,7),(30,49,47,7),(50,69,42,7),(70,200,36,6)],
             "female":[(18,29,28,5),(30,49,29,5),(50,69,26,5),(70,200,23,4)]},
    "push_up": {"male":[(18,29,30,12),(30,49,22,11),(50,69,15,9),(70,200,9,7)],
                "female":[(18,29,18,9),(30,49,14,8),(50,69,9,6),(70,200,5,5)]},
    "chair_stand": {"male":[(18,29,33,6),(30,49,31,6),(50,69,27,5),(70,200,22,5)],
                    "female":[(18,29,31,6),(30,49,29,6),(50,69,25,5),(70,200,20,5)]},
}
# 予後エビデンス順の重み (握力最強, 腕立て, SRT, 椅子)。測定済みテストで再正規化。
COMPOSITE_WEIGHTS = {"grip":0.35, "push_up":0.25, "srt":0.20, "chair_stand":0.20}

def fitness_norm(test_key, age, sex) -> tuple[float,float] | None
def fitness_percentile(test_key, value, age, sex) -> float | None   # pct_from 利用
def srt_percentile(value) -> float | None   # 0-10 → 0-100 線形 (目安)
def composite_fitness(per_test_pct: dict[str,float|None]) -> dict | None
    # {score: 0-100, contributions:[{key,pct,weight}], n_tests}
    # 重み加重平均、測定済みのみで重み再正規化。1件も無ければ None。
```

### 3. overview への反映 (`build_overview`)
- 各テスト entry に `distribution: {mean, sd, percentile}`(連続3種のみ。SRTは None だが
  percentile は srt_percentile で内部計算し composite に使う)。
- overview に `composite: {score, percentile_label, contributions} | None`。
- 年齢/性別が norms に無い → distribution/composite は None(現行 evaluable と同じ前提)。

### 4. フロント
- **共通化**: `DistributionPanel` の釣鐘描画を `frontend/src/components/BellCurve.tsx` に抽出し、
  体型・体力の両方で再利用(DRY)。
- **総合体力スコア**: `FitnessTestPanel` 先頭に `CompositeScoreBanner`
  (0-100 + 内訳バー[各テストの寄与])。
- **個別**: 連続3種の `TestCard` に小さな釣鐘 + 「同年代◯パーセンタイル」。
  SRT は現行バンドのまま(釣鐘なし)。
- `api.ts`: `FitnessTestEntry` に `distribution`、`FitnessOverview` に `composite` を追加。

## データフロー
```
build_overview → 各テスト percentile(fitness_percentile / srt_percentile)
  → composite_fitness(加重平均, 測定済みで再正規化)
  → overview.composite + 各 test.distribution
  → CompositeScoreBanner + 個別釣鐘
```

## エラー処理・エッジ
- 年齢/性別未設定 or norms 無 → distribution/composite None(絶対値・バンドのみ)。
- 未測定テストは composite の重みから除外し、残りで再正規化。
- 全テスト未測定 → composite None。
- SRT は釣鐘を出さない(段階評価)。

## テスト (pytest)
`backend/tests/test_fitness_test.py` 追記 / `test_population_norms.py`:
- `pct_from`: 平均で50、単調、クランプ。
- `fitness_percentile`: grip 既知 mean→50、欠損(age/sex)→None。
- `srt_percentile`: 0→0, 10→100, 単調。
- `composite_fitness`: 重み加重平均が正しい、未測定テストで再正規化、全欠損→None。
- `build_overview`: composite と test.distribution が入る(プロフィール設定時)。

## デプロイ
DB 変更なし(読み取り+計算のみ)。pytest・`npm run build` 後、既存手順でデプロイ。
