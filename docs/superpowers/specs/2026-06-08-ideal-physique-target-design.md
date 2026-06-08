# 理想体型シルエットから目標を自動計算・保存

日付: 2026-06-08 / 依頼: 「身長・性別・理想体型シルエット画像で目標体重を自動計算するUI」

## 決定事項 (ユーザー確認済み)
- 画像方式: **校正済みシルエットを選ぶ** (アップロード+AI推定は不採用。画像1枚から体脂肪率の
  絶対値は測れないため、体脂肪率×体型でタグ付けした参照シルエットを選ぶ方式が誠実)。
- 反映範囲: **保存してアプリ全体に反映** (resolve_profile 層を新設し env を上書き)。

## 1. 計算コア (`app/scoring/body_composition.py`, 純関数)

FFMI (Fat-Free Mass Index) ベース:
```
height_m = height_cm / 100
ffmi_raw = ffmi_normalized - 6.1 * (1.8 - height_m)   # 身長補正の逆算
lbm_kg   = ffmi_raw * height_m**2
weight   = lbm_kg / (1 - body_fat_pct/100)
bmi      = weight / height_m**2
```
- `compute_target(height_cm, body_fat_pct, ffmi_normalized) -> {weight_kg, bmi, lbm_kg}`
- ガードレール `assess(weight, bmi, body_fat_pct, sex) -> {level, warnings[]}`:
  - BMI < 16 → "保存不可" (重度低体重)
  - BMI < 18.5 → warning「低体重域」
  - 体脂肪 < (男10 / 女16) → warning「持続困難・ホルモン影響」
- 性別は体脂肪の健康下限と参照体型のシルエット形状に効く。

参照シルエット定義 (UI と共有する定数):
- 体型 (列): 細身 ffmi_norm 18 / 細マッチョ 20 / マッチョ 22
- 体脂肪 (行): 10 / 12 / 15 / 18 / 22 %

## 2. 永続化: `user_profile` テーブル + resolve_profile

- 単一行テーブル `user_profile` (id=1 固定): height_cm, sex, target_weight_kg,
  target_body_fat_pct, body_fat_tolerance_pct, ffmi_normalized (記録用), 全て nullable。
- `app/scoring/profile.py: resolve_profile() -> ResolvedProfile`:
  DB 行があればその値、無ければ `get_settings()` のデフォルトにフォールバックして返す
  (dataclass、フィールド名は settings と同じ)。
- 目標値を読む消費箇所を resolve 経由へ:
  - llm/client.py (persona, achievement series)
  - scoring/domains.py (health achievement)
  - scoring/recompute.py (body_fat 採点)
  - scoring/nutrition.py (TDEE/PFC)
  - api/dashboard.py → wellbeing_alerts へ渡す target_weight/lower
  既存の `get_settings()` はそのまま、**プロファイル系フィールドだけ** resolve に差し替える。

## 3. API (`app/api/profile.py`)

- `GET /api/profile` → `{height_cm, sex, target_weight_kg, target_body_fat_pct,
  ffmi_normalized, source: "db"|"default"}`
- `PUT /api/profile` body `{height_cm?, sex?, target_weight_kg, target_body_fat_pct,
  ffmi_normalized?}` → バリデーション (BMI≥16) 後 upsert、保存後に当日 recompute をトリガー、
  resolve 済みプロファイルを返す。異常値は 422。

## 4. フロント

`PhysiqueTargetSection` (折りたたみ、既定で閉、LifeSection 付近):
- 身長 number 入力 (プリフィル) + 性別トグル。
- **体型 × 体脂肪のシルエットグリッド**。各セル = パラメトリック SVG (`Silhouette.tsx`):
  - 胴/腹の幅 = body_fat に比例、肩/腕の幅 = ffmi に比例、性別で骨格を変える。
  - セル選択で即時に体重・BMI を計算表示 (クライアント側で同じ式)。
- 選択セルの体重・BMI・警告を下部サマリに。「この体型を目標にする」→ PUT /api/profile。
- 計算式はバックエンドと一致させ、保存値はサーバが再計算してソースに採用。

## テスト
- body_composition: 既知値 (165cm/15%/ffmi17 → 既知体重)、BMI 下限フラグ、性別別体脂肪下限。
- resolve_profile: DB 行優先、無ければ settings、部分 null のフォールバック。
- API: PUT 保存→GET 反映、BMI<16 で 422、source 表示。
- frontend ビルド (型) で Silhouette/Section の健全性。

## 非対象 (YAGNI)
- アップロード画像/AI 推定、年齢・安静時心拍の UI 編集 (env 維持)、複数プロファイル。
