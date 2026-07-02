# 就寝前の介入トラッカー & n-of-1 効果分析

## 目的

就寝前の介入（耳栓・アイマスク・ノーズブリーズ〔鼻呼吸ストリップ〕・口テープ）を毎晩記録し、
それぞれが睡眠の質を統計的に有意に改善するかを本人データで検証する。単一被験者（n-of-1）実験。

## 方針（ユーザー確定事項）

- **ハイブリッド運用**: 普段は記録するだけ。複数介入が交絡して各効果を分離できないときだけ、
  アプリが「今夜は◯◯だけ外して検証」と切り分けを提案する。
- 主アウトカム = Garmin **sleep_score**（見出し判定）。副 = 睡眠効率・深睡眠・夜間HRV。
- 配置は**睡眠タブ**（`SleepDriverPanel` の隣）。

## 既存資産の再利用

- 統計コア: `scoring/migraine_stats.py` の `permutation_test`（両側並べ替え検定・小標本は厳密列挙）と
  `benjamini_hochberg`（FDR補正）。scipy 不要、numpy は既存。
- 記録の型: `SubjectiveCheckin`（`date` 主キーの日次 upsert）+ `api/checkin.py` の部分更新パターン。
- 分析の型: `scoring/sleep_drivers.py`（ドライバー→睡眠アウトカムを検定→tier化→今夜の推奨）。
  ただし二値介入は中央値分割ではなく **「着けた/外した」で直接群比較** するため、専用モジュールにする
  （`sleep_drivers.py` には手を入れない）。
- 記録UI: `CheckinCard.tsx`（タップ即保存・楽観更新）。分析UI: `SleepDriverPanel.tsx`（tier濃淡・
  accumulating表示・今夜やること）。

## データモデル

`backend/app/models/health.py` に追加、`models/__init__.py` に登録。テーブルは `db.create_all()` が
起動時に自動作成（マイグレーション不要・additive）。

```python
class SleepInterventionLog(Base):
    """就寝前の介入の夜次ログ。date PK = その夜（起床日、SleepSession.date と一致）。
    値: True=着けた / False=外した / None=未記録。分析は True/False の夜だけ使う。"""
    __tablename__ = "sleep_intervention_log"
    date: Mapped[date]            # PK
    earplugs / eyemask / nose_strip / mouth_tape: Mapped[bool | None]
    note: Mapped[str | None]      # 任意
    updated_at: Mapped[datetime | None]
```

**「外した(False)」を明示保存する理由**: 分析は「着けた夜 vs 外した夜」の比較。未記録(None)と
「外した(False)」を区別しないと、着けた夜しか貯まらず比較群が作れない。フロントは記録時に4項目
すべてを明示 bool で送り、タップされなかった介入は False として確定させる。

## 日付の紐付け（TZ）

`SleepSession.date` は Garmin の起床日基準。就寝前（夜）に記録した介入は、その眠りの起床日に紐付ける。
サーバ側 `_target_date()`:

- JST の現在時刻が **18:00 以降 → 翌日**（今夜眠って明朝起きる → 起床日は明日）
- **18:00 未満 → 当日**（朝〜昼に前夜分を記録 → 起床日は今日）

これで `SleepInterventionLog.date == SleepSession.date` が一致し、分析で直結できる。UI では混乱を避けるため
「◯/◯の夜」（起床日−1）と表示し、API は解決済み date も返す。

## API

`backend/app/api/sleep_intervention.py`（`main.py` に include_router 1行追加）。

- `POST /api/sleep-intervention` — 夜次 upsert。Body: `earplugs/eyemask/nose_strip/mouth_tape`(bool|None)、
  `reset`(bool, 全項目Noneに戻す)、`date`(任意, ISO)。None は「据え置き」だがフロントは常に4 bool 全部送る。
  応答は GET と同形。
- `GET /api/sleep-intervention?days=30` — `{ tonight: {date, display_label, earplugs, ...}, items: [...] }`。
  `tonight` は `_target_date()` の行（無ければ未記録）。
- `GET /api/sleep/interventions` — 分析結果（読み取り専用、`scoring.sleep_interventions.analyze()`）。

## 分析ロジック

`backend/app/scoring/sleep_interventions.py`。DB読み取り部（`_collect`）と純関数（`_analyze_rows`）を分離し、
純関数をユニットテスト可能にする。

- 介入: `earplugs/eyemask/nose_strip/mouth_tape`。アウトカム: `sleep_score`(主)・`efficiency`・`deep_min`・
  `hrv_overnight`。効率は `total/(total+awake)*100`（`SleepSession` に効率カラムが無いため都度計算）。
- `_collect(target)`: 直近120日で SleepSession と介入ログが両方ある夜について
  `{sleep_score, efficiency, deep_min, hrv_overnight, earplugs:bool|None, ...}` の行を作る。
- `_analyze_rows(rows)`:
  - 各 介入 × アウトカム で、True群 と False群 に分ける。各群が `_MIN_GROUP`(=3) 以上のときだけ
    `permutation_test(did, didnt)` を実行。`diff = mean(did) - mean(didnt)`（全アウトカム高いほど良い → diff>0 で改善）。
  - 全テストをまとめて BH-FDR。tier: `q<0.05`→strong / `p<0.1`→suggestive / `p<0.25`→trend / else weak。
  - 介入ごとに見出し `verdict`: sleep_score の結果を第一に `improves`/`worsens`/`no_effect`/`insufficient`。
    `primary`（sleep_scoreの検定結果）と `outcomes`（全アウトカムの結果）を付す。`n_did`/`n_didnt` も返す。
  - **交絡検知（ハイブリッド提案）**: (a) ある介入の False夜 が `_MIN_GROUP` 未満（＝ほぼ毎晩着けている）→
    「今夜は◯◯を外して検証」。(b) 2介入がほぼ常に同時オン/オフ（不一致夜が `_MIN_GROUP` 未満）→
    「今夜はどちらか一方だけ」。最優先の1件を `suggestion` として返す。
- `analyze(target)`: `n_nights < _MIN_NIGHTS`(=6) なら `status="accumulating"` と `remaining`。以降は
  `status="analyzed"` で介入リスト + suggestion + `reliability`(high≥45/medium≥21/low)。

戻り値:
```
{ status, n_nights, remaining?, reliability?,
  interventions: [ { key, label, n_did, n_didnt, verdict,
                     primary: {outcome,outcome_label,diff,p,q,tier}|null,
                     outcomes: [ {outcome,outcome_label,diff,p,q,tier}, ... ] }, ... ],
  suggestion: { text, reason } | null }
```

## フロントエンド

`lib/api.ts` に型（`SleepInterventionTonight`, `SleepInterventionRecord`, `SleepInterventionAnalysis`）と
メソッド（`sleepInterventionGet` / `sleepInterventionSet` / `sleepInterventions`）を追加。

- **`SleepInterventionCard.tsx`**（記録）: 4トグル（耳栓/アイマスク/ノーズブリーズ/口テープ）。
  未記録なら淡色ゴースト。タップすると `sleepInterventionSet` で **4項目すべて明示 bool** を送り（タップ分=True、
  他=現状 or False）、その夜を記録済みにする。小さな「クリア」で `reset`。「◯/◯の夜」を見出しに表示。
  楽観更新は CheckinCard を踏襲。保存後 `["sleep-intervention"]` と `["sleep-interventions"]` を invalidate。
- **`SleepInterventionPanel.tsx`**（分析）: `accumulating` は残り夜数。`analyzed` は介入ごとに
  verdict バッジ（改善/悪化/効果なし/データ不足）+ sleep_score の差分・p・n、副アウトカムを tier 濃淡で。
  `suggestion` があれば「今夜の検証」として目立たせる。
- 配置: `Today.tsx` 睡眠タブ、`SectionHeader "就寝前の介入 × 睡眠の質"` の下に Card → Panel、その後に既存の
  睡眠ドライバー。

## テスト

`backend/tests/test_sleep_interventions.py`（DB不要・`_analyze_rows` を直接呼ぶ）:
- 明確に効く介入（True夜=高スコア / False夜=低スコア）→ verdict `improves`・tier strong。
- 効かない介入（両群同分布）→ `no_effect`。
- 片群が MIN_GROUP 未満 → `insufficient`。
- ほぼ毎晩オン（False夜不足）→ `suggestion` が「外して検証」を返す。
- 2介入が常に同時 → `suggestion` が「一方だけ」を返す。

## 非目標（YAGNI）

- 介入項目のユーザー定義追加（4種固定。将来は additive にカラム追加）。
- 自動ランダム割付の強制（提案のみ。着ける/外すは本人判断）。
- sleep_score 欠測夜の補完（欠測夜はその介入×アウトカムから単に除外）。
```
