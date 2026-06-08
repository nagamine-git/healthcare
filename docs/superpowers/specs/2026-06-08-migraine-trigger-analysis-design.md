# 頭痛(片頭痛)要因分析: 発症時刻プロファイル + ケースクロスオーバー

日付: 2026-06-08 / 依頼: 「頭痛の要因を都度分析。気圧か、カフェイン離脱か、実は何も寄与していないのか。
統計的に有意なものだけ知りたい。時間帯(午前/午後)まで細かく」

## 背景と制約

- 頭痛は `migraine_episode` (started_at, ended_at, severity) に手動記録。現状 5 件 / 4 日 (約18日)。
- **小サンプルなので有意性主張は今は不可能**。ユーザー合意: 仕組みは今作り、頭痛が一定数たまるまでは
  「診断保留」と表示する。有意ゼロも誠実に伝える。
- 気圧は現状ライブ取得のみで履歴保存なし → Open-Meteo 履歴 API でバックフィルが必要。

## Part 1: 発症時刻プロファイル (記述的・ゲートなし)

各エピソードの発症時刻 (JST hour) を集計:
- `circadian.circular_mean_hour` / `circular_sd_hours` で「平均◯時ごろ・ばらつき±◯h」。
- 4 区分のカウント: 早朝〜午前(4-11) / 昼〜午後(11-17) / 夕〜夜(17-23) / 深夜(23-4)。
- n が小さくても「分布」として誠実 (有意性主張ではない)。最頻区分を peak として返す。

## Part 2: トリガー分析 (時刻対応ケースクロスオーバー・有意性ゲート)

### データ単位
「頭痛日 vs 非頭痛日」ではなく **発症時刻起点の曝露ウィンドウ** を使う:
- ケース: 各発症の直前 24h ウィンドウ。
- 対照: 非頭痛日それぞれの **同じ時刻** を起点とした 24h ウィンドウ (time-of-day を揃え、
  カフェイン・気圧の日内変動という交絡を除去する time-stratified case-crossover)。

### 候補要因 (測った全部を返す → 「何も無い」も示せる)
| key | 曝露指標 (ウィンドウ内) | 仮説方向 |
|---|---|---|
| pressure_drop | ウィンドウ内の最大気圧低下量 (hPa) | 大きいほど誘発 |
| caffeine_withdrawal | 個人7日平均mg − ウィンドウ内mg (不足量) | 不足で離脱頭痛 |
| caffeine_excess | ウィンドウ内mg − 個人7日平均 | 過多で誘発 |
| sleep_short | 直前夜の睡眠時間 (分) | 短いほど誘発 |
| hrv_low | その日の HRV (last_night_avg) | 低いほど誘発 |
| alcohol_prev | 前日の純アルコール g | 多いほど誘発 (現状0件→データ不足) |

各要因はデータが揃わない (ケース/対照が一定数未満、または全欠損) 場合 `insufficient` を返しスキップ。

### 検定
- 連続値: ケース群 vs 対照群の平均差を観測統計量とし、**並べ替え検定** (ケース/対照ラベルを
  シャッフルして帰無分布を作り両側 p 値)。小サンプル・非正規でも妥当。反復は決定的にするため
  シード固定 (Math.random 不使用、index ベース)。
- **多重比較補正**: 検定した要因数に対し Benjamini-Hochberg (FDR)。補正後 q<0.05 を「有意」。
- 効果量: ケース平均 − 対照平均 (符号で方向)、および対照分布における percentile。

### 有意性ゲート
- 頭痛エピソード < `MIN_EPISODES=10`: 判定保留。`status="accumulating"`, `remaining=10-n`。
- ≥10: 有意要因のみ返す。全要因が非有意なら `status="no_significant_factor"` で明示。

## API

`GET /api/migraine/triggers` →
```json
{
  "episode_count": 5,
  "onset_profile": {
    "mean_hour": 15.3, "sd_hour": 2.1, "peak_bucket": "昼〜午後",
    "buckets": [{"label":"早朝〜午前","count":1}, ...]
  },
  "status": "accumulating" | "no_significant_factor" | "has_factors",
  "min_episodes": 10,
  "remaining": 5,
  "factors": [
    {"key":"pressure_drop","label":"気圧低下","direction":"誘発",
     "case_mean":8.1,"control_mean":2.3,"p":0.03,"q":0.04,"significant":true}
  ],
  "tested": ["pressure_drop","caffeine_withdrawal",...]
}
```
onset_profile は常に返す (記述的)。factors は status により空/有意のみ。

## 気圧履歴の保存

- `MetricSample(source="open-meteo", metric_key="surface_pressure_hpa", ts, value)` に hourly 保存。
- バックフィル: Open-Meteo Archive API (`archive-api.open-meteo.com/v1/archive`, hourly=pressure_msl,
  start_date/end_date) で過去分を一括。`bin` か CLI から実行。
- 定期: 既存の気圧スナップショット取得時 (forecast の past_days=2 分) も同じ key で upsert し前進。

## フロント

`MigrainePanel` の下部か専用 `MigraineTriggerPanel`:
- 発症時刻プロファイル: 4区分のミニ棒 + 「平均15時ごろ・昼〜午後に集中」。
- status=accumulating: 「📊 データ蓄積中 — 有意判定にはあと N 件の頭痛記録が必要」+ 追跡中の要因名。
- has_factors: 有意要因を方向・p値つきで。
- no_significant_factor: 「測定した6要因のうち統計的に有意なものは現時点でありません」。

## テスト
- circadian プロファイル: 既存 circular 関数の再利用。区分カウント。
- permutation test: 既知データで p の単調性、完全分離で小 p、差なしで大 p。決定性 (同入力同出力)。
- BH 補正: 既知 p 列で順序と閾値。
- ケースクロスオーバー曝露抽出: 発症時刻起点ウィンドウ、対照の時刻整合。
- ゲート: n<10 で accumulating、有意ゼロで no_significant_factor。
- 気圧バックフィル: フェイク archive レスポンスから MetricSample 書き込み・upsert。
