# Healthcare Dashboard — 仕様

シングルユーザー向けの「今日のコンディション採点 + アドバイス」Web サービス。Tailscale tailnet 内からのみアクセス可能。

## 1. ゴール

- Garmin / Apple Health (HealthKit) / オムロン体組成計 / MyFitnessPal の健康データを単一サーバーに集約する
- 直近 28 日のベースラインに対する乖離をもとに **0–100 の総合スコア**と 5 つのサブスコアを毎時計算する
- 毎朝 1 回、Claude API による短い行動アドバイスを生成し、ダッシュボードに表示する
- PC / スマホ両方から見やすいレスポンシブ UI を提供する

## 2. 非目標 (MVP では実装しない)

- 長期トレンドグラフ専用ページ、年単位ダッシュボード
- Slack / iOS プッシュ通知
- 自動バックアップ
- マルチユーザー、外部公開、認可制御 (tailnet 信頼モデル)
- iOS 専用ネイティブアプリ（Health Auto Export 経由で HealthKit を取り込む）

## 3. アーキテクチャ概要

```
[iPhone: Health Auto Export] --HTTPS POST--> [FastAPI /ingest/health-auto-export]
[Garmin Connect] <----python-garminconnect---- [APScheduler: garmin_sync 毎時]
                                                       │
                                                       ▼
                                              [SQLite ヘルスケアDB]
                                                       │
                          [APScheduler: scoring/baseline/llm] ←┘
                                                       │
[Browser via tailnet HTTPS] ---- [Tailscale serve sidecar] ---- [FastAPI /api/*]
                                                       │
                                              [/api/today, /api/timeseries]
```

## 4. データソースと同期方針

| ソース | 取得方法 | 頻度 | 主な指標 |
|---|---|---|---|
| Garmin | `python-garminconnect` 直接 | 毎時 5 分 | 睡眠スコア, HRV (overnight), Body Battery, 安静時心拍, ストレス, ワークアウト, トレーニングロード, VO2max, Body Composition |
| Apple Health | Health Auto Export (iOS app) → REST POST | アプリ設定次第 (推奨 6h ごと) | HealthKit 全般 (歩数, 心拍, 睡眠分析, 体重, 体脂肪率, 食事, 水分摂取 等) |
| オムロン体組成計 | OMRON connect → Apple Health → HAE 経由 | (HAE 経由) | 体重, 体脂肪率, 骨格筋率, BMI |
| MyFitnessPal | MyFitnessPal → Apple Health → HAE 経由 | (HAE 経由) | エネルギー, タンパク質, 脂質, 炭水化物, 水分 |

## 5. 採点ロジック

5 つのサブスコアを 0–100 に正規化し、**加重幾何平均** で総合スコアに合成する。

| サブスコア | 計算方法 | 重み |
|---|---|---|
| Sleep | Garmin sleep_score を直接採用。なければ duration / efficiency / deep+rem ratio の加重平均 | 3 |
| HRV | 当夜 HRV を直近 28 日平均に対する z-score → `clamp(50 + 25·z, 0, 100)` | 2 |
| Body Battery | 朝 6:00 時点の値をそのまま 0–100 として使用 | 2 |
| Training Load | 7 日 EWMA / 28 日 EWMA = ACWR。0.8–1.3 で 85、0.5–0.8 と 1.3–1.5 で 65、外側 40 | 2 |
| Weight | 7 日中央値 vs 28 日中央値の偏差 / 28 日 σ。±1σ で 80、±2σ で 50、それ以上で 30 | 1 |

合成式: `score = (∏ subᵢ^wᵢ) ^ (1 / Σwᵢ)`

データが 28 日溜まるまでは「ベースライン学習中」表示でスコアは null。各サブスコアは欠損時 null、合成時は欠損サブスコアを除外した重みで再計算する。

## 6. LLM コメント

- モデル: `claude-haiku-4-5` (デフォルト)、env `LLM_MODEL` で切替可能
- 呼び出しタイミング: 毎日 06:30 に自動 + ダッシュボードからの手動再生成 (1 日 3 回まで)
- プロンプト構造:
  1. system (cached): コーチペルソナ + サブスコアの意味 + 出力フォーマット規定 (200 字以内、絵文字なし、根拠を 1 つ示す)
  2. system (cached): 直近 28 日のベースライン要約 JSON
  3. user: 今日のサブスコア・主要メトリクス・前日差分
- 失敗時はルールベースのテンプレ文言にフォールバックし `llm_comment.model = "fallback"` を記録

## 7. データモデル (SQLite)

### 生データ層
- `metric_sample` — long-format。`(source, metric_key, ts)` UNIQUE。HR / 歩数 / ストレス / 食事など全 fine-grain メトリクス
- `sleep_session(date PK, source, total_min, deep_min, rem_min, light_min, awake_min, sleep_score, hrv_overnight_avg, raw_json)`
- `hrv_daily(date PK, last_night_avg, weekly_avg, status, baseline_low, baseline_high)`
- `body_battery(ts PK, value, charged, drained)` + `body_battery_daily(date PK, max, min, end_of_day, morning_value)`
- `workout(id PK, source, start, end, type, duration_s, distance_m, kcal, training_load, avg_hr, max_hr, raw_json)`
- `weight_sample(ts PK, weight_kg, body_fat_pct, muscle_kg, water_pct, source)`

### 集計層
- `daily_summary(date PK, steps, active_kcal, resting_hr, vo2max, training_status)`
- `daily_score(date PK, sleep_sub, hrv_sub, bb_sub, load_sub, weight_sub, total, version, computed_at)`
- `llm_comment(date, generated_at, model, prompt_hash, comment, PRIMARY KEY(date, generated_at))`

### 運用層
- `source_sync(source PK, last_synced_at, last_error, cursor_json)`

## 8. API

| Method | Path | 用途 |
|---|---|---|
| GET | `/healthz` | 死活監視 |
| POST | `/ingest/health-auto-export` | HAE からの POST 受信 (Bearer 認証) |
| GET | `/api/today` | 今日の総合スコア + サブスコア + 主要メトリクス + アドバイス |
| GET | `/api/timeseries?metric=&from=&to=` | 任意メトリクスの時系列 (MVP はサブスコア・体重・睡眠時間) |
| POST | `/admin/garmin/sync` | 手動 Garmin 再同期 |
| POST | `/admin/recompute` | 手動 recompute (date 指定可) |
| POST | `/admin/llm/regenerate` | LLM コメント再生成 |

認証: `/healthz` 以外は tailnet 信頼。`/ingest/*` のみ Bearer (`HAE_INGEST_TOKEN`)。

## 9. ジョブ

| ジョブ | スケジュール | 内容 |
|---|---|---|
| `garmin_sync` | `5 * * * *` | Garmin から前回 cursor 以降を取得し upsert |
| `recompute_today` | `15 * * * *` | サブスコア・総合スコア再計算 |
| `morning_advice` | `30 6 * * *` | LLM コメント生成 |
| `baseline_refresh` | `0 3 * * *` | 28 日 baseline 再計算 |
| `vacuum` | `0 4 * * 0` | SQLite VACUUM |

## 10. 技術スタック

- Backend: Python 3.12, FastAPI, SQLAlchemy 2.x, APScheduler, anthropic SDK, python-garminconnect
- Frontend: React 18 + TypeScript + Vite + TanStack Query + Tailwind CSS + recharts
- DB: SQLite (WAL mode)
- Container: Docker Compose, Tailscale 公式イメージ sidecar
- Secrets: 1Password CLI (`op run --env-file`)

## 11. ディレクトリ構造

```
healthcare/
├── SPEC.md                    # この文書
├── README.md                  # ユーザー向け手順
├── docker-compose.yml
├── .env.tmpl                  # op run 用テンプレ
├── .gitignore
├── tailscale/
│   └── serve-config.json
├── backend/
│   ├── pyproject.toml
│   ├── Dockerfile
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── db.py
│   │   ├── logging.py
│   │   ├── scheduler.py
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── api/
│   │   ├── ingest/
│   │   ├── scoring/
│   │   └── llm/
│   └── tests/
└── frontend/
    ├── package.json
    ├── tsconfig.json
    ├── vite.config.ts
    ├── tailwind.config.js
    ├── Dockerfile
    └── src/
        ├── main.tsx
        ├── App.tsx
        ├── pages/
        ├── components/
        └── lib/
```

## 12. 受け入れ基準

- `pytest` がグリーン
- `cd frontend && npm run build` が成功
- `docker compose config` が valid
- `op run --env-file=.env.tmpl -- docker compose up -d` 後、`https://<host>.<tailnet>.ts.net` が 200 を返す (実機検証はユーザー)
- `POST /ingest/health-auto-export` にサンプル JSON を投げると `daily_summary` と `metric_sample` に書き込まれる
- 28 日分のシードデータがあれば `/api/today` が 5 サブスコアと総合スコアを返す
