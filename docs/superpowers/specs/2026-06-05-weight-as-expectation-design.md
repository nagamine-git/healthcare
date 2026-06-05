# ライフドメイン: 重み＝期待水準モデル

日付: 2026-06-05 / 承認: nagamine

## 背景

従来の重みはライフスコア加重平均の寄与度のみだった。ユーザーの直感は
「重みを下げる＝そのドメインへの要求も下がる」。例えば瞑想 weight 0.5 なら
目標 15 分ではなく 7.5 分で満点になるべき。

加重平均と達成度/weight 補正を併用すると分子で weight が打ち消され
「重みを上げるほどスコアが下がるだけ」の退化が起きるため、集計は単純平均にする。

## 仕様

### スコア計算 (`app/scoring/domains.py: compute_life`)

```
ドメインスコア = min(100, 生達成度 / weight)   # weight > 0
ライフスコア   = ドメインスコアの単純平均（achievement が null または weight=0 のドメインは除外）
```

- weight 0.5 → 半分の成果で満点（瞑想なら実効目標 7.5 分）
- weight 2.0 → 2 倍要求（生 100 点でも 50 点止まり）
- weight 0 → 「今は対象外」。ライフスコア集計から除外。achievement は生値を返す。

### API (`/api/life` 系)

- `achievement` = 補正後スコア（フロント表示値）
- `raw_achievement` = 生達成度（新規フィールド）
- 瞑想の `detail` は実効目標で表示: `f"{分:.0f}/{15*weight:g}分"`

### LLM プロンプト (`app/llm/prompts.py`)

「life_score は重み付き総合」→「重みは期待水準（達成度/weight 補正後の単純平均）」に修正。

## 変えないもの

- プリセット定義の数値・DB スキーマ・フロントエンド UI
- 各ドメインの生達成度関数（meditation_achievement 等）

## テスト

- weight<1 で補正後スコアが上がる / weight>1 でキャップされる
- weight=0 のドメインが集計から除外される
- raw_achievement が API レスポンスに含まれる
- 瞑想 detail が実効目標表示になる
