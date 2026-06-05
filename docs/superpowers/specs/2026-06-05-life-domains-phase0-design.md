# ライフドメイン化 フェーズ0(コア)— 要件定義

日付: 2026-06-05
位置づけ: healthcare を「健康専用」から「自己目標理想管理」へ進化させる第一歩。
既存の理想達成度モデル([2026-06-04-trend-ideal-achievement-design.md])を上位レイヤー(ライフドメイン)に拡張する。

## 目的

複数のライフドメイン(健康・瞑想・将来は読書/学習/speech)それぞれの「理想への達成度(0-100)」を、
その時々で変えられる**重み**で統合し、(1)今日の配分提案、(2)達成度ダッシュボード、の両輪を提供する。

フェーズ0の領域は **健康(既存)+ 瞑想(`mindful_minutes` で自動)** の2つ。これでコア枠組みを動かす。

## スコープ(フェーズ0)

含む: ライフドメイン抽象 / 健康・瞑想の達成度 / 重みプリセット+手動スライダー / ライフスコア /
LLM配分提案 / ダッシュボードセクション。
含まない(後続フェーズ): speech(speech-coach連携)/ 学習(GitHub commit・Anki)/ 読書 / 目標ベース自動重み。

## ライフドメイン抽象

ドメインキー: `health`, `meditation`(将来 `reading`, `learning`, `speech`)。
各ドメインは「達成度(0-100, 高いほど理想に近い)」を返す。DB非依存の計算は `domains.py`、
DB読み出しは既存の `trend_sources` / `MetricSample` を使う。

- **健康ドメイン達成度** = 既存トレンドの6指標(sleep/hrv/energy/load/weight/body_fat)の
  **最新達成度の平均**(null除外)。理想達成度モデルと一貫。`trend_sources.collect_raw_series` +
  `achievement.py` を再利用し、各指標の最新達成度を平均する。
- **瞑想ドメイン達成度** = 当日(JST)の `mindful_minutes` 合計を、目標分への upper 達成度に変換。
  `achievement.upper_achievement(total_min, floor=0, good=settings.meditation_target_min)`。
  目標 `meditation_target_min` のデフォルトは 15(config、後調整可)。データが無い日は達成度 null。

## 重み(プリセット + 手動スライダー)

- **プリセット**(config 定数 `DOMAIN_WEIGHT_PRESETS`): ドメイン→重みのセット。初期:
  - `balanced`: health 1.0 / meditation 1.0
  - `recovery`(回復優先): health 2.0 / meditation 1.0
  - `mindful`(内省優先): health 1.0 / meditation 2.0
  (将来ドメイン追加時にプリセットへ追記)
- **現在の重み**: 新テーブル `domain_weight(domain TEXT PK, weight REAL)` に保存。
  未設定ドメインは既定 1.0。プリセット適用で全ドメインを上書き、スライダーで個別更新。

## ライフスコア

`life_score = Σ(weightᵢ × achievementᵢ) / Σ(weightᵢ)`(achievement が null のドメインは分母分子とも除外)。
0-100。「理想への総合接近度」。

## API

- `GET /api/life` →
  ```json
  {
    "life_score": 71.2,
    "domains": [
      {"key":"health","label":"健康","achievement":68.0,"weight":1.0,"detail":"6指標の達成度平均"},
      {"key":"meditation","label":"瞑想","achievement":80.0,"weight":2.0,"detail":"12/15分"}
    ],
    "presets": [{"key":"balanced","label":"バランス"}, ...],
    "generated_at":"..."
  }
  ```
- `PUT /api/life/weights` body `{"weights": {"health": 1.0, "meditation": 2.0}}` → 保存して更新後の状態を返す。
- `POST /api/life/preset/{name}` → プリセットの重みを `domain_weight` に書き込み、更新後の状態を返す。

ドメインのキー・ラベル・達成度関数の対応は `domains.py` の `LIFE_DOMAINS` に集約(DRY、API/LLMで共有)。

## LLM 配分提案

`client.py` の `today_payload` に `life_domains`(各ドメインの達成度・重み)と `life_score` を追加。
`prompts.py` に「# ライフドメインと今日の配分」セクションを足し、**重みの高いドメインを優先して**
今日の行動を配分するよう指示(例: 重み高=英語/瞑想を主、健康は維持)。フェーズ0では health/meditation のみ。

## ダッシュボード(frontend)

- 新規 `LifeSection.tsx`: 先頭に **ライフスコア**(大きく)、その下に各ドメインの達成度バー +
  重みスライダー、上部にプリセットのチップ(タップで適用)。
- `Today.tsx`: 最上部(StaleBanner/アラートの直後、「今日のアクション」の前)に `<LifeSection />`。
  既存の健康詳細(トレンド/メトリクス/各記録パネル)はその下に維持。

## データモデル

`backend/app/models/health.py` に追加:
```python
class DomainWeight(Base):
    __tablename__ = "domain_weight"
    domain: Mapped[str] = mapped_column(String(32), primary_key=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
```
`create_all` で起動時に追加(既存DB影響なし)。

## テスト

- `backend/tests/test_domains.py`: 健康達成度(seed した sleep/weight 等 → 6指標平均)、
  瞑想達成度(mindful_minutes seed → 目標達成度)、データ欠損で null。
- `backend/tests/test_life_api.py`: `GET /api/life`(domains/life_score/presets)、
  `PUT /api/life/weights`(保存)、`POST /api/life/preset/{name}`(プリセット適用)、ライフスコアの加重平均。
- frontend: `npm run build`(型・ビルド)。

## ビルド・デプロイ

[[healthcare-deploy-ops]] の通り。backend は `hc-backend-test` イメージで pytest+ruff、
frontend は `npm run build`、デプロイは `! op signin && bin/up-mac.sh`(ユーザー実行)、PWAリロード2回。
作業ブランチ `feat/life-domains` → 検証後 main へ FF → push。
