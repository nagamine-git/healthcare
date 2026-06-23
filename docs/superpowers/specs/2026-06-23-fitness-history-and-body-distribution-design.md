# フィットネス記録の履歴管理 + 体型の母集団分布 設計

作成日: 2026-06-23

独立した2機能をまとめて記す。各々別タスク群として実装する。

---

## 機能A: フィットネステスト記録の履歴閲覧・編集・削除

### 背景
`FitnessTestPanel` は最新値しか見せず、過去の測定を一覧・修正・削除する導線が無い。
誤記録の訂正や推移の確認ができるようにする。対象はフィットネステスト記録のみ。

### アーキテクチャ
- **バックエンド (最小変更)**:
  - `GET /api/fitness/history/{test_key}` の各 item に `id` を追加 (削除UI用)。他は不変。
  - 編集 = 既存 `POST /api/fitness/results` (UPSERT: test_key × performed_on) を流用。
    過去日の値を同じ performed_on で再POSTすると上書き。新エンドポイント不要。
  - 削除 = 既存 `DELETE /api/fitness/results/{result_id}`。
- **フロント**:
  - `TestCard` に「履歴」折りたたみを追加。`api.fitnessHistory(testKey)` で
    日付・値 (+握力は左右 detail) を新しい順に一覧。
  - 各行に **編集** (値をインライン入力 → `api.fitnessRecord` に performed_on 付きでUPSERT)
    と **削除** (確認 → `api.fitnessDelete(id)`)。
  - 記録/編集/削除後は `["fitness-tests"]` と該当 `["fitness-history", key]` を invalidate。
  - `api.ts`: `FitnessHistory["items"]` に `id: number` 追加、`fitnessDelete(id)` 追加。

### テスト (pytest)
`backend/tests/test_fitness_api.py`:
- history の各 item が `id` を含む。
- `DELETE /results/{id}` で当該行が history から消える。
- 同 test_key × performed_on の再POSTで値が上書き (件数が増えない)。

---

## 機能B: 体型の母集団 percentile 分布 (BMI / 体脂肪率 / FFMI)

### 背景・目的
体重・体脂肪率の「自分の現在地」を、日本人 同年代・同性の母集団に対する percentile で示す。
体型はBMI単独では筋肉質さを捉えられないため、手元データ (体重・体脂肪率・身長) から
正確に計算できる **3指標** を出す:

- **BMI** = 体重 / 身長²。母集団: 国民健康・栄養調査 (公的統計、確度高)。
- **体脂肪率 %** = 体組成計の実測。母集団: 文献の近似 (目安)。
- **FFMI** (除脂肪量指数) = 除脂肪量 / 身長²。除脂肪量 = 体重 ×(1 − 体脂肪率/100)。
  BMIが見ない筋肉質さを表す。母集団: 文献の近似 (目安)。

### アーキテクチャ

#### 1. 母集団基準値 + percentile (`backend/app/scoring/population_norms.py`)

性別 × 年代帯の `(mean, sd)` をコードに保持し、正規分布 CDF で percentile を返す。

```python
# BMI: 平成28年 国民健康・栄養調査 (e-Stat 0003224178) 男性実測。女性は同調査の近似。
# 体脂肪率/FFMI: 文献ベースの近似 (目安)。年代帯 = [下限, 上限] (歳)。
NORMS: dict[str, dict[str, list[tuple[int, int, float, float]]]] = {
    "bmi": {
        "male": [(18,29,22.6,3.7),(30,49,23.9,3.6),(50,69,24.0,2.9),(70,200,23.4,2.9)],
        "female": [(18,29,20.7,2.8),(30,49,21.7,3.4),(50,69,22.9,3.5),(70,200,23.1,3.7)],
    },
    "body_fat": {  # 目安 (文献近似)
        "male": [(18,29,16.0,5.0),(30,49,20.0,5.0),(50,69,23.0,5.0),(70,200,24.0,5.0)],
        "female": [(18,29,25.0,6.0),(30,49,28.0,6.0),(50,69,31.0,6.0),(70,200,32.0,6.0)],
    },
    "ffmi": {  # 目安 (文献近似)
        "male": [(18,29,18.9,1.9),(30,49,18.9,1.9),(50,69,18.3,1.9),(70,200,17.6,1.9)],
        "female": [(18,29,14.6,1.6),(30,49,14.6,1.6),(50,69,14.2,1.6),(70,200,13.8,1.6)],
    },
}

def norm_for(metric, age, sex) -> tuple[float, float] | None: ...   # 年代帯から (mean, sd)
def percentile(metric, value, age, sex) -> float | None:           # Φ((x-μ)/σ)*100
    # Φ(z) = 0.5*(1+erf(z/√2)); 0-100 にクランプ。
def metric_source(metric) -> str:  # "国民健康・栄養調査" | "文献の目安"
```

各指標の `(mean, sd)` も返し、フロントが分布曲線を描けるようにする。

#### 2. 体型指標の算出 (`backend/app/scoring/body_metrics.py` or population_norms 内)

```python
def bmi(weight_kg, height_cm) -> float | None
def ffmi(weight_kg, body_fat_pct, height_cm) -> float | None   # 除脂肪量/身長²
```

#### 3. API (`backend/app/api/physique.py` に追加 or `body_distribution.py` 新規)

`GET /api/physique/distribution`:
- 最新 `WeightSample` (weight_kg, body_fat_pct) + `resolve_profile()` (age, sex, height) を取得。
- 各指標について `{key, label, unit, value, mean, sd, percentile, source}` を算出。
  値が出せない指標 (体脂肪率欠損 → body_fat/ffmi 不可) は `value=None` で返す。
- 目標マーカー: target_weight → target BMI、target_body_fat_pct を同梱 (任意)。
- 年齢/性別/身長が無ければ `evaluable: false` で指標は値のみ (percentile/分布なし)。
- `main.py` にルータ登録 (未登録なら)。

レスポンス例:
```json
{
  "evaluable": true,
  "metrics": [
    {"key":"bmi","label":"BMI","unit":"","value":24.1,"mean":23.9,"sd":3.6,
     "percentile":52,"source":"国民健康・栄養調査","target":23.0},
    {"key":"body_fat","label":"体脂肪率","unit":"%","value":18.0,"mean":20.0,"sd":5.0,
     "percentile":34,"source":"文献の目安","target":15.0},
    {"key":"ffmi","label":"FFMI (筋肉量指数)","unit":"","value":19.8,"mean":18.9,"sd":1.9,
     "percentile":68,"source":"文献の目安","target":null}
  ]
}
```

#### 4. フロント (`frontend/src/components/DistributionPanel.tsx`)

- physique タブ内 (`BodyCompositionMap` の近く) に配置。
- 指標ごとにベルカーブ: `mean ± 3sd` を 41 点で正規 pdf を JS 生成 → recharts `AreaChart`。
  現在値に縦 `ReferenceLine` + 「同年代・同性で ◯パーセンタイル」ラベル。目標があれば破線マーカー。
- 出典バッジ: BMI=「国民健康・栄養調査」、体脂肪率/FFMI=「目安」。
- `api.ts`: 型 `PhysiqueDistribution` + `api.physiqueDistribution()` 追加。
- 正規 pdf は純粋関数 `normalPdf(x, mean, sd)` を `frontend/src/lib/stats.ts` に切り出し。

### テスト (pytest) `backend/tests/test_population_norms.py`
- `percentile` が単調増加 (値↑ → percentile↑)。
- 平均値で percentile ≈ 50。
- 年齢/性別欠損で `None`。
- `bmi` / `ffmi` の計算 (既知入力→既知出力、身長0や欠損で None)。
- 体脂肪率欠損時に body_fat/ffmi が value=None。
- API: evaluable=false 時に分布を出さない。

### エラー処理・エッジ
- WeightSample が無い (未取込): metrics は value=None、UIは「記録待ち」。
- 体脂肪率欠損: BMI のみ算出、体脂肪率/FFMI は value=None。
- プロフィール (年齢/性別/身長) 欠損: evaluable=false、percentile/分布なし・絶対値のみ。
- percentile は 0-100 にクランプ。

## デプロイ
両機能とも DB 変更・新規テーブルなし (機能Bは読み取りのみ、機能Aは既存API流用)。
実装・pytest・`npm run build` 通過後、`docker compose --env-file .env.runtime up -d --build`。
