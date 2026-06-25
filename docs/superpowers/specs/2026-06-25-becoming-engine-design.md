# Becoming エンジン + フライホイール/North Star 設計

- 日付: 2026-06-25
- ステータス: 確定(実装着手可)
- 関連: [[compass-feature]] [[garden-feature]]
- 位置づけ: 「becoming プログラム」第1ブロック。フル再デザイン(#2)は後続の別プログラム。
  本ブロックは現行 UI スタイルで「使える」状態まで作る。

## 1. 目的

身体・アイデンティティ・日々の行動の三層を一つの因果ループ(フライホイール)として束ね、
「良いコンディション → 盲点を埋める行動 → 理想への前進」が回っているかを見せ、到達予測
(North Star)を出す。健康スコア/Compass/庭とは別軸の横断モジュール。

## 2. 重要な制約(正直に扱う)

`IdentityDimensionScore` は現在地を1行 upsert で履歴を持たない。よってアイデンティティの
トレンド(前進の速さ)は**今から snapshot を貯めないと出せない**。コンディション・庭は既存
履歴からバックフィルできるが、dim_estimates のトレンドは**前向き(これから)**で、最初の
数週は ETA 低信頼。ETA は保守的に幅・信頼度つきで提示する。

アイデンティティ前進の測り方は「**実測変化を主・行動を補助**」(オーナー決定):
overall_proximity の実測 Δ を主指標、庭の focus 付き行動量を先行指標(期待前進)として併用。

## 3. データモデル(`models/health.py`、additive)

```python
class BecomingSnapshot(Base):
    __tablename__ = "becoming_snapshot"
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    condition: Mapped[float | None]            # DailyScore.total
    garden_focus: Mapped[float | None]         # その日の focus(0..1)
    garden_intensity: Mapped[float | None]     # その日の intensity
    overall_proximity: Mapped[float | None]    # build_gap_report["overall"]
    dim_estimates: Mapped[dict | None] = JSON  # {dimension_id: current_estimate}(履歴の素)
    captured_at: Mapped[datetime]
```

## 4. config(臨床/個人区分に従う)

```python
becoming_good_condition_threshold: float = 70.0   # personal: 「動ける」良好日の閾値
becoming_trajectory_window_days: int = 90         # tuning: 傾き推定の窓
becoming_min_snapshots_for_eta: int = 14          # tuning: これ未満は低信頼
```

## 5. ロジック(`scoring/becoming/`、純関数中心)

### `snapshot.py`
- `capture_snapshot(session, date) -> BecomingSnapshot`: DailyScore.total / garden_daily
  (focus は `cell_focus(contributions)`)/ build_gap_report の overall と各次元 current を読み upsert。
- `backfill_snapshots(session, days) -> int`: 過去日の condition・garden を埋める
  (dim_estimates は履歴が無いので過去日は None。トレンドは前向きのみ)。

### `metrics.py`(純・DB非依存)
- `loop_week(snaps: list[Snap], good_threshold) -> dict`:
  - `capacity_utilization`: condition>=good_threshold の日のうち garden_intensity>0 の割合(良好日0なら None)
  - `action_alignment`: garden_intensity>0 の日の平均 garden_focus(活動日0なら None)
  - `identity_movement`: overall_proximity が非Nullな snapshot の (最後 - 最初)(2点未満なら None)
  - `diagnosis`: `wasted_capacity`(良好日多いのに行動少) / `spinning`(整合高いのに前進<=0) /
    `flywheel_turning`(活用・整合・前進すべて良) / `building`(データ不足/中間)

### `trajectory.py`(純・DB非依存)
- `dimension_slope(points: list[(date, value)]) -> float | None`: 最小二乗の傾き(units/day)。2点未満 None。
- `project(snaps, targets, weights, window_days, min_snapshots) -> dict`:
  - 重み付き各次元の傾き → 目標到達までの日数 `time_to_target=(target-current)/slope`(slope<=0 は inf)
  - `eta_days` = 重み>0 の次元の中で最大の time_to_target(=ボトルネック)。全て inf/不足なら None。
  - `bottleneck_dimension` = 重み付き次元のうち time_to_target 最大のもの。
  - `confidence`: dim_estimates を持つ snapshot 数 >= min_snapshots なら "medium"、未満 "low"。
  - `per_dimension`: [{id, current, target, slope_per_day, time_to_target_days}]

## 6. LLM(`llm/becoming.py`)

- `generate_one_move(state) -> dict`: becoming 状態(ボトルネック次元・診断・今日のコンディション・
  既存の弱点ヒント)を渡し、**今日いちばん効く1アクション + if-then** を生成。
  既存 `llm/identity.py` と同じ AsyncAnthropic + tool_use(`tool_choice` 強制)パターン。
  返り: `{move, if_then, dimension_id, rationale}`。api_key 未設定なら呼ばずエンジンの構造化提案で代替。

## 7. API(`api/becoming.py`、ハンドラは薄く)

- `GET /api/becoming` → `{date, loop_week, trajectory, history: [snapshot...], weakest}`
- `POST /api/becoming/one-move` → `{move, if_then, dimension_id, rationale}`(LLM)
- `POST /api/becoming/backfill` → `{filled}`(初回や手動再構築用)

## 8. スケジューラ

- `becoming_snapshot_job`(日次、recompute/garden の後 = 例 `35 * * * *`):当日 snapshot を upsert。
- lazy import、coalesce/max_instances=1。

## 9. フロント(`pages/Becoming.tsx`, `#becoming`、現行スタイル)

- **フライホイール カード**: 3指標(資本活用率・行動整合度・前進量)+ 診断文
  (「動けた日に攻めたか/努力が盲点に向いていたか/実際に近づいたか」)。
- **今日の一手**: ボタンで `one-move` 生成 → move + if-then 表示。
- **North Star カード**: ETA(信頼度・幅つき。低信頼は明示)+ ボトルネック次元 + per-dimension 簡易リスト。
- `App.tsx` に `#becoming` ルート、`Today.tsx` に導線、`lib/api.ts` に型 + wrapper。

## 10. テスト

- `metrics.py`/`trajectory.py` を合成 snapshot で純関数テスト(DB/ネット不要)。
- `snapshot.py` を in-memory DB でテスト(capture/backfill 冪等)。
- API 形状テスト(`app_client` fixture)。
- 既存スイートが落ちないこと。

## 11. デプロイ / 使える状態

- `db.create_all()` で新テーブル生成。`#becoming` を開き、初回は backfill で過去の
  コンディション・庭が埋まる。snapshot が貯まるほど ETA の信頼度が上がる。
- 本番デプロイは [[deploy-mechanism]](`.env.runtime` 再利用 + compose build)。

## 12. YAGNI(やらないこと/後続)

- フル再デザイン(#2)は本ブロックに含めない(現行スタイルで使える状態にする)。
- ETA の高度な不確実性モデル(ベイズ等)はやらない。最小二乗 + 信頼度ラベルで十分。
- 介入効果の個人学習(どの作品/if-then が効くか)は後続ブロック。
