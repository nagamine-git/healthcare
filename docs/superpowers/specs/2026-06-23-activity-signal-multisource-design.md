# 活動/外出シグナル(全ソース相互補完) 設計

作成日: 2026-06-23

## 背景・目的
Garmin は着けない日があり、iPhone も持たない瞬間がある。どの単一デバイスにも依存せず、
**その日に存在する最良のソースから「動いたか」「外に出たか」を推測**し、**どのソースも
無い日は『不明』(ゼロではない)** とする補助シグナルを作る。片頭痛/ウェルビーイング相関の
素材や、日々の活動把握に使う。ネイティブアプリ・バックグラウンドセンサーは不要
(iPhone のモーションコプロセッサと Garmin が省電力で計測済みのデータを取り込むだけ)。

## 利用可能なデータ (本番点検済み)
- `metric_sample` (source=hae): `step_count`, `walking_running_distance`, `flights_climbed`,
  `apple_exercise_time`, `heart_rate_avg` 等 — iPhone/Apple Health 由来 (Garmin非依存)。
- `metric_sample` (source=garmin): `intensity_minutes_moderate/vigorous`, `floors_up`,
  `heart_rate_avg`, stress 等。
- `workout` (garmin): type に walking/rucking(屋外) / strength_training/boxing(屋内) 等。
- `daily_summary.steps`: 日次歩数 (ソース混在の集計)。

## 設計原則
1. **相互補完**: 歩数は `daily_summary.steps` と hae `step_count` 日合計の**最大値**を採用
   (合算は二重計上になる)。距離・ワークアウトは各ソースを足し合わせる。
2. **欠損 ≠ ゼロ**: その日に歩数・距離・ワークアウト・HR のいずれも無ければ
   `moved=None / went_outside=None / confidence="none"` (不明)。決して False にしない。
3. **段階的劣化**: Garmin(連続HR/強度) > iPhone(歩数/距離) > 疎 の順で confidence を下げる。

## アーキテクチャ

### 1. スコアリング (`backend/app/scoring/activity_signal.py`)

```python
@dataclass(frozen=True)
class DayEvidence:
    date: date
    steps: float | None            # 最良ソース採用
    distance_m: float | None       # walking_running_distance + workout距離
    workouts: tuple[str, ...]      # その日の workout type 群
    outdoor_workout: bool          # 屋外種別が1つ以上
    exercise_min: float | None     # apple_exercise_time / intensity_minutes
    has_hr: bool                   # HRサンプル有 (デバイス装着の証跡)
    sources: tuple[str, ...]       # 寄与した source ("garmin"|"hae"|"daily_summary")

OUTDOOR_TYPES = {"walking","running","hiking","cycling","rucking","trail_running","walk","run"}
MOVE_STEPS = 1500          # これ以上 or 距離/ワークアウト有 → 動いた
MOVE_DISTANCE_M = 800
OUTDOOR_DISTANCE_M = 1500  # 屋外ワークアウト無くても、この距離なら外出とみなす

def classify(ev: DayEvidence) -> dict:
    # 純粋関数。coverage 無→ unknown。
    # moved   = steps>=MOVE_STEPS or distance>=MOVE_DISTANCE_M or workouts or exercise_min>0
    # outside = outdoor_workout or distance>=OUTDOOR_DISTANCE_M
    # confidence: none / low / medium(iPhoneあり) / high(Garmin連続HR or 屋外ワークアウト)
    # 返り: {date, moved, went_outside, confidence, steps, distance_m, sources}

def gather_day(session, day: date, tz) -> DayEvidence:   # DB読み取り
def recent_signals(days: int = 14) -> list[dict]:        # 各日 classify
```

`classify` は純粋関数として単体テストし、`gather_day` は薄い DB 集約に留める。

### 2. API (`backend/app/api/activity.py`)
- `GET /api/activity/signal?days=14` → `{"days": [classify結果...]}` (新しい日が先頭)。
- `main.py` にルータ登録。

### 3. フロント (`frontend/src/components/ActivitySignalCard.tsx`)
- 直近N日を行で: 日付・動いた(歩アイコン)・外出(太陽/家アイコン)・confidence バッジ・歩数/距離。
- `moved/went_outside == null` の日は **「不明」**(灰)で明示し、False と区別。
- `api.ts` に `ActivitySignal` 型 + `api.activitySignal(days)`。
- 配置: 健康タブ (活動の文脈)。

## エラー処理・エッジ
- ソース皆無の日 → unknown (None)。UI は「不明」。
- 歩数の二重計上防止 = 最良ソース採用 (合算しない)。
- タイムゾーン: 単一ユーザー JST 前提で `date(ts)` 集約 (境界の微差は補助シグナルとして許容)。
- 屋内ワークアウト (strength/boxing) は「動いた」には効くが「外出」には効かない。

## テスト (pytest) `backend/tests/test_activity_signal.py`
- `classify`: 歩数十分→moved、距離十分→outside、屋外ワークアウト→outside、
  屋内のみ→moved=True/outside=False、coverage無→全て None・confidence none。
- confidence: Garmin連続HR→high、iPhoneのみ→medium。
- API: ルートが 200 で days を返す (DBに合成サンプル投入)。

## デプロイ
DB 変更なし (読み取りのみ)。pytest・`npm run build` 後、既存手順でデプロイ。
