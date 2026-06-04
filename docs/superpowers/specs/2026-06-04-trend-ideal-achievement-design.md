# トレンド再設計 — 理想達成度と傾向の可視化

日付: 2026-06-04
前提: [2026-05-31-trend-visualization-design.md](2026-05-31-trend-visualization-design.md) を置き換える(supersede)。
初版はトレンドを daily_score のサブスコア(離散値)で表示していたが、(1)一部指標が「理想乖離」でなく
別概念を測っていた、(2)離散値ゆえトレンドが階段状で傾向が見えない、という問題があった。

## 目的

各健康指標を「理想値/理想帯からの乖離度(連続 0-100 の達成度)」で評価し、生値グラフに理想ゾーンと
回帰トレンドラインを重ねて、「理想に近づいているか(改善トレンドか)」を一目で分かるようにする。

## 評価軸(確定)

- 各指標カードに **生値グラフ + 理想ゾーンバンド + 回帰トレンドライン** を描く。
- 同時に **理想達成度(連続 0-100)** とその **改善/悪化方向** をバッジで併示する。
- 採点ロジック(`daily_score` の総合スコア)は **変更しない**。達成度はトレンド表示専用に別計算する。

## 指標ごとの理想定義と達成度

達成度は2つの型で全指標を表現する(`achievement.py` の純粋関数)。

### 型A: 目標帯 `band_achievement(value, lo, hi, softness)`
理想帯 `[lo, hi]` の内側で 100、外側は帯端からの距離 `d` に対しローレンツ関数で滑らかに減衰:
```
d = 0 if lo <= value <= hi else min(|value-lo|, |value-hi|)
achievement = 100 / (1 + (d / softness)**2)   # d=softness で 50 点、d=2*softness で 20 点
```

### 型B: 片側(高いほど良い)`upper_achievement(value, floor, good)`
```
value <= floor → 0 / value >= good → 100 / 間は線形
achievement = clamp((value - floor) / (good - floor) * 100, 0, 100)
```

### 指標パラメータ

| 指標 | 生値 (raw) | 型 | パラメータ | 理想ゾーン表示 |
|------|-----------|----|-----------|--------------|
| 睡眠 | 睡眠時間(分) | 合成 | 下記 | 帯 420–540 分 |
| HRV | last_night_avg(ms) | B(ベースライン比) | `z=clamp((v-mean)/std,-2,2)`, `ach=clamp(50+25z)` | ベースライン平均の水平線 |
| エネルギー | 朝 Body Battery | B | floor=20, good=80 | good=80 の水平線 |
| 運動負荷 | ACWR | A | lo=0.8, hi=1.3, softness=0.3 | 帯 0.8–1.3 |
| 体重 | 体重(kg) | A | lo=目標−1, hi=目標+1, softness=1.5 | 帯 目標±1kg |
| 体脂肪率 | 体脂肪率(%) | A | lo=目標−tol, hi=目標+tol, softness=2×tol | 帯 目標±tol |

`目標体重` = `settings.target_weight_kg`、`目標体脂肪率` = `settings.target_body_fat_pct`、
`tol` = `settings.body_fat_tolerance_pct`。HRV のベースライン(mean,std)は `baselines.build_baseline()` を使う。

### 睡眠の合成達成度(確定)
```
time_ach    = band_achievement(total_min, 420, 540, softness=90)
quality_ach = garmin_sleep_score があればそれ(0-100)
              無ければ睡眠効率ベース: (in_bed-awake)/in_bed*100 と (deep+rem)/in_bed の質スコアの平均
sleep_ach   = 0.4 * time_ach + 0.6 * quality_ach    # 質側に重み
              quality_ach が無い日は time_ach のみ(重み再正規化)
```
重み 0.4/0.6 は `achievement.py` の定数にし、後で調整可能にする。

## 方向(改善/悪化)の判定

**達成度の系列**(生値ではなく)に対し、直近7点の線形回帰の傾きを取り、初版 `trends.py` の
`_direction(values, higher_is_better=True)` を流用する。達成度が上がる=理想に近づく=`improving`(緑)、
下がる=`declining`(赤)、ほぼ水平=`stable`(灰)。全指標で達成度は「高いほど良い」に統一されるため、
型A/Bや指標の向きを意識せず方向判定できる。

`prev_day_change` / `week_over_week` も達成度系列ベースで算出する。

## 回帰トレンドライン(グラフ用)

**生値系列**の線形回帰を計算し、両端2点 `{start:{date,value}, end:{date,value}}` を返す。
フロントは recharts の `ReferenceLine` または2点の `Line` で点線描画する。週次(週平均)表示時は回帰線は出さない。

## データフローとモジュール分割

責務を分けて小さく保つ:

- **`backend/app/scoring/achievement.py`(新規)**: 理想定義の定数 + 達成度の純粋関数
  (`band_achievement`, `upper_achievement`, `sleep_achievement`, `hrv_achievement`, など指標別ラッパ)。DB 非依存。
- **`backend/app/scoring/trends.py`(改修)**: 回帰(`linear_regression_endpoints`)、方向・前日比・前週比(既存流用)、
  週平均。生値系列 → 達成度系列への写像ヘルパ。DB 非依存。
- **`backend/app/scoring/trend_sources.py`(新規)**: DB から各指標の生値日次系列を取得する。
  睡眠/HRV/エネルギー/体重/体脂肪率は各テーブル、ACWR は各日付で `recompute._training_load()` を呼ぶ
  `daily_acwr_series()` ヘルパ。HRV ベースラインも取得。
- **`backend/app/api/dashboard.py`(改修)**: `/api/trends` が `trend_sources` で生値を集め、
  `achievement`+`trends` で各指標の出力を組む。
- **`backend/app/llm/client.py`(改修)**: `_gather_recent_trends` を達成度ベースに更新。
- **frontend**: `TrendCard` を生値+バンド+回帰線に作り直し、`TrendBadge` は達成度方向。Today に体脂肪率追加。

## API: `GET /api/trends`

クエリ: `granularity=daily|weekly`, `days`(既定28)。返却(指標ごと):
```json
{
  "granularity": "daily",
  "generated_at": "...",
  "metrics": {
    "sleep": {
      "label": "睡眠", "unit": "分",
      "raw_series": [{"date":"2026-05-04","value":430}, ...],
      "ideal": {"type":"band","lo":420,"hi":540},
      "current_raw": 455,
      "achievement": 82.1,
      "achievement_prev_day_change": 4.2,
      "achievement_week_over_week": {"delta":6.0,"pct":7.9},
      "direction": "improving",
      "regression": {"start":{"date":"2026-05-04","value":410},"end":{"date":"2026-05-31","value":460}}
    },
    "hrv": { "ideal": {"type":"upper","good_line":62.0}, ... },
    "energy": { "ideal": {"type":"upper","good_line":80}, ... },
    "load": { "ideal": {"type":"band","lo":0.8,"hi":1.3}, ... },
    "weight": { "ideal": {"type":"band","lo":...,"hi":...}, ... },
    "body_fat": { "ideal": {"type":"band","lo":...,"hi":...}, ... }
  }
}
```
- `weekly` のとき `raw_series` は週平均、`regression` は null。
- データ不足(系列<2)は `direction=null`, `regression=null`, `achievement` は最新点があれば値・無ければ null。

メトリクスのキー: `sleep, hrv, energy, load, weight, body_fat`(初版の `total`/`body_battery` を整理。
総合スコアはトレンド対象から外す — 達成度の平均は意味が薄く、各指標の改善が見たいというのが今回の主旨)。

## エラーハンドリング / データ欠損

- 生値が欠損の日は系列に点を作らない(線が途切れる)。達成度系列も同様。
- ベースライン未学習(HRV)や目標未設定はその指標を `achievement=null, direction=null` で返し、UIは「計測中」。
- ACWR は直近14日に workout が無ければ null。

## テスト

`backend/tests/test_achievement.py`(新規):
- `band_achievement`: 帯内=100、`d=softness`で≈50、両側対称、softness 別。
- `upper_achievement`: floor/good 境界とクランプ。
- `sleep_achievement`: 質あり(重み0.6)/質なし(時間のみ)/時間が長すぎる場合に減衰。
- `hrv_achievement`: ベースライン比 z のクランプ。

`backend/tests/test_trends.py`(改修):
- `linear_regression_endpoints`: 既知系列の始点・終点。
- 達成度系列からの direction/prev_day_change/week_over_week(既存テストを達成度入力に合わせ更新)。

`backend/tests/test_dashboard_api.py`(改修):
- 生値テーブルを seed し `/api/trends` が raw_series/ideal/achievement/regression を返すこと。
- weekly で regression が null・raw_series が週平均になること。

`backend/tests/test_llm.py`(改修): `_gather_recent_trends` が達成度ベースの direction を返すこと。

frontend はテストランナーが無いため `npm run build`(tsc 型チェック + vite build)で検証。

## ビルド・デプロイ

- backend: Docker ワンオフで `pytest` + `ruff`(ローカル python が壊れているため。
  [[backend-local-python-broken]] 参照)。
- frontend: `cd frontend && npm run build`。
- デプロイ: `bin/up-mac.sh`(op で `.env.tmpl`→`.env.runtime` 解決 → `docker compose -f docker-compose.yml
  -f docker-compose.mac.yml up -d --build`、tailscale userspace で `https://healthcare.<tailnet>.ts.net` 公開)。
