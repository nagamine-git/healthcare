# 天気予報・降水確率パネル 設計

2026-06-24。Yahoo天気並みに正確な天気予報・降水確率を出す。洗濯/外出判断にも使う。

## データソース

Open-Meteo `forecast` API を **models 未指定(best_match=地点ごとの最適モデル自動選択)** で叩く。
key不要・無料・商用可。既存の気圧取得 (`integrations/weather.py`) と同じ仕組み・同じ1時間
キャッシュに乗せる。

**重要(検証済み 2026-06-24)**: `models=jma_seamless`(気象庁モデル)は降水量・気温は出すが
**降水確率 `precipitation_probability` を提供しない(全 None)**。本機能の主目的は降水確率なので
best_match を採用する。best_match は日本では高解像度モデルの合議で、降水確率込みの一貫した予報が
得られる(Yahoo天気の完全再現ではないが、降水確率を出すための現実解)。

## スコープ

**含む(この土台)**:
- 正確な天気パネル(独立した新規パネル、ホーム上部)
- 今日・明日の **時間別**(降水確率・降水量・気温・天気・湿度・風)
- **7日週間**(天気・最高/最低気温・降水確率最大)
- 今日の **傘/洗濯の素朴なひとこと**(日中9–18時JSTの降水確率最大・降水量から3段判定)

**やらない(次フェーズの別spec)**:
- 湿度・日照・風を使った本格的な洗濯指数
- 片頭痛・朝光・トレーニング助言への天気の織り込み
- 現在地切替(地点は config の WEATHER_LATITUDE/LONGITUDE 固定)

## コンポーネント

### バックエンド `integrations/weather.py`
- `get_weather_forecast(lat, lon) -> WeatherForecast | None` を追加。
  - Open-Meteo を `jma_seamless`、`timezone=Asia/Tokyo`、`forecast_days=7` で取得。
  - hourly: `temperature_2m, precipitation, precipitation_probability, weathercode, relative_humidity_2m, wind_speed_10m`
  - daily: `weathercode, temperature_2m_max, temperature_2m_min, precipitation_probability_max, sunrise, sunset`
  - 1時間キャッシュ(既存 `_CACHE` 機構を流用)。失敗時は None。
- 純粋関数(DB・ネット非依存、ユニットテスト対象):
  - `weather_code_to_label(code) -> (label, icon_key)`: WMO weathercode → 日本語天気+アイコンキー。
  - `laundry_hint(probs_daytime, precip_daytime) -> (level, text)`: 日中降水確率最大・降水量から
    `ok|caution|no` の3段+ひとこと。
  - `_shape_forecast(raw) -> WeatherForecast`: API生JSON → 整形済み構造(今日明日の時間別 + 週間)。

### API `api/weather.py`(新規ルーター)
- `GET /api/weather`: `{ summary, hourly[], daily[] }` を返す。
  - `summary`: 今日の天気・最高/最低・降水確率・`laundry`(level+text)。
  - `hourly`: 今日明日(48h)の `{time, temp, precip, precip_prob, code, label, icon}`。
  - `daily`: 7日の `{date, code, label, icon, t_max, t_min, precip_prob_max}`。
- main.py に登録。

### フロント `components/WeatherPanel.tsx`(新規)
- ホーム上部に配置(Today ページ)。`lib/api.ts` に型と fetch を追加。
- 表示: 今日サマリ(アイコン+最高/最低+降水確率+傘/洗濯ひとこと)、時間別(横スクロール:
  降水確率バー+気温+アイコン)、週間(7日リスト)。
- weathercode→アイコンは lucide-react(Sun/CloudRain/Cloud/Snowflake 等)でマップ。
- 取得失敗時は「天気を取得できませんでした」を表示(握りつぶさない)。

## テスト
`weather_code_to_label`・`laundry_hint`・`_shape_forecast`(欠損含む)を純粋関数として TDD。
API フェッチは最小限のモック。

## エラー処理
API失敗・フィールド欠損時は None / 部分表示で degrade。既存の気圧・大気質と同じ方針。
