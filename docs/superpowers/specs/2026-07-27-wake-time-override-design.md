# 起床時刻の日別指定と、逆算項目の拡張

**日付**: 2026-07-27
**対象**: healthcare (backend + frontend)

---

## 1. 目的

「何時に起きたいか」を入力したら、そこから逆算して今夜の予定が組まれるようにする。

現状すでに `scoring/sleep_plan.py:compute_tonight_plan()` が起床時刻から逆算しているが、起床時刻は
プロフィールの**恒久的な既定値** (`profile.wake_time`) しか持てない。「明日だけ 5:30 に起きたい」を
表現する手段が無い。

---

## 2. 現状の把握 (実装済みのもの)

### 2.1 逆算エンジンは既にある

`compute_tonight_plan(target)` が返すもの:

| キー | 内容 |
|---|---|
| `wake` | 起床 (= 起点) |
| `bedtime` / `bedtime_iso` | 就寝 (習慣から realistic に前倒し。日跨ぎ考慮済み) |
| `bath_start` / `bath_end` | 湯船に入る / 上がる (就寝90分前) |
| `dinner_start` / `dinner_end` | 夕食の食べ始め / 食べ終わり (就寝180分前) |

`MAX_ADVANCE_MIN = 45` — 概日リズムの前進は行動・光で 1 日 30-60 分が限界 (Burgess/Eastman) なので、
理想へ一気に飛ばさず習慣の就寝から最大45分だけ前倒しする、という設計が既に入っている。

### 2.2 起床時刻は既にユーザーが変更できる

`PATCH /api/profile` の `wake_time`、UI は設定タブの「起床時刻」(`SettingsTab.tsx`)。
ただし**恒久的な既定値**であり、日別の指定はできない。

### 2.3 この計画は 11 モジュールが参照している

`wind_down` / `meditation` / `next_action` / `dashboard` / `timeline` / `notifications`(engine, service) /
`llm/client` / `llm/workout_review` / `api/wind_down` / `api/meditation`。

**この事実が設計の中心**: 起床時刻の差し替えを `compute_tonight_plan` の 1 箇所で行えば、
カフェイン締切も呼吸法の判定も通知タイミングも自動で追随する。各モジュールへの個別対応は不要。

---

## 3. スコープ

### 含む
- 日別の起床時刻オーバーライド (その日だけ)
- 逆算項目の追加: **カフェイン締切 / 運動締切 / 光を落とす時刻**
- `TonightPlanPanel` での起床時刻の編集 UI と、追加項目の表示

### 含まない (YAGNI)
- カレンダーからの自動逆算 (Google Calendar 連携は既にあるが、今回は手入力に絞る)
- 曜日ごとの繰り返しパターン (平日/休日) — 必要になってから
- Google Calendar への予定ブロック書き込み

---

## 4. 設計

### 4.1 日別オーバーライド

**モデル** — `models/health.py` に追加:

```python
class SleepPlanOverride(Base):
    """その夜だけの起床時刻。日付キーなので過ぎれば自然に効かなくなる。"""
    __tablename__ = "sleep_plan_override"
    date: Mapped[date] = mapped_column(Date, primary_key=True)  # 起床する日 (JST)
    wake_time: Mapped[str] = mapped_column(String(5))           # "HH:MM"
    updated_at: Mapped[datetime] = mapped_column(DateTime)
```

`db.py` の軽量マイグレーション (`_apply_lightweight_migrations`) で追加する。既存 SQLite と互換。
このリポジトリには Alembic が無く additive な変更のみ許容される、という既存制約に従う。

**キーの意味**: `date` は「**起床する日**」。就寝日ではない。`compute_tonight_plan` は既に
「深夜0時台に呼ばれたら target 自身の朝が起床」という日跨ぎ判定 (`in_progress_night`) を持っており、
その判定後の `wake_dt.date()` を引き当てキーにすれば、日跨ぎの扱いが既存ロジックと自動的に一致する。

**適用箇所**: `compute_tonight_plan()` 内で `prof.wake_time` を読む 1 箇所だけ。

```python
wake_t = _parse_hhmm(prof.wake_time)
# ... 既存の in_progress_night 判定で wake_dt を決めた後 ...
# その日のオーバーライドがあれば差し替える (無ければ既定値のまま)
```

オーバーライドの引き当ては DB 参照になるが、`compute_tonight_plan` は既に `_habitual_phase()` で
DB を読んでいるので新たな制約は生じない。

**API**:
- `GET /api/sleep-plan/override?date=YYYY-MM-DD` → `{date, wake_time} | null`
- `PUT /api/sleep-plan/override` `{date, wake_time}` → upsert
- `DELETE /api/sleep-plan/override?date=YYYY-MM-DD` → 既定に戻す

### 4.2 逆算項目の追加

すべて `compute_tonight_plan` の返り値へ**キー追加のみ**。既存キーは変更しない (後方互換)。

| 項目 | 計算 | 定数の出所 |
|---|---|---|
| `caffeine_cutoff` | `bedtime - caffeine_cutoff_hours_before_bed` | **既存** `config.caffeine_cutoff_hours_before_bed = 6.0` |
| `exercise_cutoff` | `bedtime - exercise_to_bed_lead_min` | **新規 config 化**。現在 `sleep_drivers._action_text` に「就寝3時間前」がハードコードされているので、config に出して**両者で共有**する (二重定義を作らない) |
| `dim_light_at` | `bedtime - dim_light_lead_min` | **新規** (clinical: 就寝90分前。夕食終わり=180分前と就寝の中間で、メラトニン分泌の抑制を避ける) |

いずれも clinical 定数 (誰にでも共通の生理) として `config.py` に置く。CLAUDE.md の
「clinical/physiological と personal target を分ける」規約に従う。

### 4.3 UI

`TonightPlanPanel`:
- 起床時刻をタップ → 時刻ピッカー → その日だけ変更。「既定に戻す」を併設
- オーバーライド中は既定と違うことが分かる表示 (バッジ等)
- 追加 3 項目を既存の時刻リストに並べる

---

## 5. エラー処理

- オーバーライドの取得失敗は**既定値へフォールバック**する。計画そのものが出ないより、既定で出る方が良い
  (`compute_tonight_plan` は 11 モジュールが依存しており、ここで例外を投げると広範囲が壊れる)
- `wake_time` は `^([01]\d|2[0-3]):[0-5]\d$` で検証 (既存の profile API と同じパターン)
- 過去日へのオーバーライドは受け付けるが意味を持たない (自然に無視される)

## 6. テスト

- `compute_tonight_plan`: オーバーライド有/無で `wake` と `bedtime` が変わること
- **日跨ぎ**: 深夜 0 時台に呼んだとき、オーバーライドの引き当てキーが「その朝」になること
- 追加 3 項目が `bedtime` から正しい差分になっていること
- 運動締切の定数を `sleep_drivers` と共有しても既存の助言文が変わらないこと
- API: upsert / delete / 不正な `wake_time` の拒否

## 7. リスク

- **`compute_tonight_plan` は 11 モジュールが参照する中核**。返り値のキー追加は後方互換だが、
  `wake` の値が変わると通知や LLM 助言の内容も変わる。これは意図した挙動 (それが目的) だが、
  実データで wind_down / meditation / next_action が追随することを fp7 で確認する
- 運動締切の定数を config へ移す際、`sleep_drivers._action_text` の既存文言を壊さないこと
