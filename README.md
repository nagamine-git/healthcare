# Healthcare Dashboard

Tailscale tailnet 内からのみアクセスする、シングルユーザー向けの「今日のコンディション採点 + アドバイス」ダッシュボード。

詳細仕様は [SPEC.md](./SPEC.md) を参照。

## 構成

```
[iPhone Health Auto Export] ─POST/JSON─▶ [FastAPI /ingest/health-auto-export]
[Garmin Connect] ◀──python-garminconnect── [APScheduler 毎時]
                                                    │
                                                    ▼
                                          [SQLite (WAL) + 採点 + LLM]
                                                    │
[Browser via tailnet HTTPS] ── tailscale serve sidecar (443→80) ── nginx → FastAPI
```

- Backend: Python 3.12 / FastAPI / SQLAlchemy / APScheduler / anthropic SDK / python-garminconnect
- Frontend: React + Vite + TanStack Query + Tailwind + recharts
- Container: docker compose (`backend`, `frontend`, `tailscale` sidecar)
- Secrets: 1Password CLI (`op run`)

## ユーザーが用意するもの

`.env.tmpl` は **`Personal` Vault にある実アイテム** (UUID 指定) を参照する状態にコミット済み。
新たに作る/設定するのは以下のみ。

1. **1Password CLI (`op`)** — `op signin` 済みであること
2. **1Password アイテム (Personal Vault)** — 既に存在するもの:
   - `anthropic key` (UUID: `coa3nmxh...`) → password に Anthropic API キー
   - `Garmin` (UUID: `l3zw5muz...`) → username/password に Garmin Connect ログイン情報
   - `TailScaleAuthKey` (UUID: `d6k2tduo...`) → password に Tailscale auth key
   - `HealthAutoExport Bearer` (UUID: `3jtudssy...`) → password に HAE 用 Bearer (本セットアップで作成済み)
3. **Tailscale 設定** — admin で `tag:healthcare` を作って ACL に追加し、auth key にも付与
4. **iPhone 側 Health Auto Export** ([App Store](https://apps.apple.com/app/id1115567069))
   - REST API automation を **新規追加**
   - URL: `https://<hostname>.<tailnet>.ts.net/ingest/health-auto-export`
   - Header に `Authorization` キーで `Bearer <op item get "HealthAutoExport Bearer" --reveal の値>`
   - Data Type: Health Metrics, All Selected
   - Export Format: JSON, Export Version: v2, Summarize Data: ON
   - Sync Cadence: 6 hours (推奨)
5. **オムロン体組成計** — OMRON connect アプリで Apple Health に同期する設定（既存）
6. **MyFitnessPal** (任意) — Apple Health に栄養データを書き出す設定

### .env.tmpl の解決チェック

```bash
op run --env-file=.env.tmpl -- env | grep -E '^(ANTHROPIC|GARMIN|HAE_|TS_AUTHKEY)='
```

5 行すべてに値が入っていれば OK。

## 初回セットアップ

```bash
# 1. 環境疎通の事前チェック (1Password 参照が全部解けるか)
bin/verify.sh

# 2. ビルド & 起動 (op run が env を解決して docker compose に渡す)
bin/up.sh

# 3. Garmin の初回ログイン (MFA に対応するため対話実行)
bin/garmin-login.sh

# 4. ブラウザで https://<hostname>.<tailnet>.ts.net を開く
```

### Tailscale ACL の確認

`tag:healthcare` を auth key で使うには、ACL ファイルに `tagOwners` が必要。
admin の Access controls → Edit file で以下を含めること:

```json
{
  "tagOwners": {
    "tag:healthcare": ["tsuyoshi.nagamine@efg-technologies.com"]
  }
}
```

(タグを Tags ページから作った場合は自動で書かれていることが多い)

## 開発

```bash
# Backend (Python 3.12)
cd backend
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e '.' --group dev
.venv/bin/python -m pytest                  # 75 tests
.venv/bin/python -m ruff check app/ tests/
APP_DATA_DIR=/tmp/hc HAE_INGEST_TOKEN=t ANTHROPIC_API_KEY=t \
  .venv/bin/uvicorn app.main:app --reload

# Frontend
cd frontend
npm install
npm run dev          # http://localhost:5173 (proxies /api to localhost:8000)
npm run build
```

## CLI

`docker compose exec backend python -m app.cli ...` で実行可。

| サブコマンド | 用途 |
|---|---|
| `garmin-login` | Garmin Connect への対話ログイン（MFA 必要時） |
| `sync-garmin` | Garmin から手動で取得 |
| `recompute [YYYY-MM-DD]` | 指定日のスコアを再計算（省略時は本日） |
| `regenerate-advice [YYYY-MM-DD]` | LLM コメントを強制再生成 |

## Healthcare が触ってよい Calendar イベント

LLM が再提案で時刻/内容を **上書きできる** イベントは、以下のいずれか:

1. Healthcare の「Calendar に追加」で作ったイベント (自動で `extendedProperties.private.hc_managed=1` 付与)
2. ユーザーが手動で作った既存イベントで、**説明欄に `[hc-adjustable]` を含む** もの

例: 「【筋トレ】全身：基礎代謝最大化メニュー」「【有酸素＆腹筋＆ふくらはぎ】...」を Healthcare の判断で時間/内容調整させたい場合は、各イベントの説明欄に `[hc-adjustable]` を 1 行入れておく。

調整不可 (会議、固定予定) のイベントは LLM が触らず、そこを避けて提案する。

## openclaw 連携 (Telegram critical 通知)

健康指標が critical な日だけ Telegram に飛ばす。健康な日は完全サイレント。

job 定義の真実源は `systemd/openclaw-healthcare-watch.json` (cron 式 / agent / message 等)。openclaw-gateway が動いている状態で `~/.openclaw/cron/jobs.json` を直接編集しても in-memory state から書き戻されて消えるため、必ず CLI 経由で登録する。

```bash
./bin/install-openclaw-job.sh   # 再実行可能。同名ジョブがあれば削除してから再登録
```

判定ロジック (どれか 1 つで通知): `priority=critical` の advice、Body Battery 朝 < 30、睡眠 < 5h、HRV BAD、ACWR ≥ 1.5、score < 40、`sync.last_error` あり。詳細は JSON 内 `payload.message`。即時実行は `openclaw cron run <id>` (id は `openclaw cron list` で確認)。

## ライセンス・スコープ

個人専用。Garmin Connect の利用規約を遵守し、自分のデータのみを取り扱う。
