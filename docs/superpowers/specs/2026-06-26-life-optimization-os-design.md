# Life Optimization OS 設計(目的→目標→ドメイン→行動)

- 日付: 2026-06-26
- ステータス: 確定(フェーズ1 実装着手可)
- 関連: [[becoming-program]] [[compass-feature]] [[garden-feature]]、既存 `life-domains-phase0`
- コンセプト: **「より良い人生のための選択と行動を最適化する」**。健康に限らず自己研鑽全体が対象。
  `healthcare` という枠は小さい(リネームは後続フェーズで安く実施)。

## 1. 4層モデル(縦の意図ライン)

```
Layer 0  目的 Purpose : 価値観×マインドセット(Compass)= 不変の北極星(WHY)
Layer 1  目標 Goals   : 目的に連なる中期ターゲット(指標・期限/複数ドメイン横断)。重点ウェイトの源泉
Layer 2  ドメイン      : MECE な life areas。各葉に 達成度 / 理想 / 維持フロア
Layer 3  行動 Action  : garden の手札。ドメイン達成度を日々動かす(HOW)
```

- 重点ウェイト = **目標由来**(明示)+ **Compass ギャップ由来**(盲点補正)の合成。
- 維持フロア = 目標と独立に「最低限守る下限」。割ったら警告。

## 2. MECE ドメイン木(資本/状態で排他化)

```
ドメイン
├─ 身体資本   : 睡眠 / 運動(有酸素・筋トレ)/ 栄養 / 体組成 / 回復(自律神経)
├─ 精神状態   : ストレス・情動 / 内省(瞑想・ジャーナリング)
├─ 知的資本   : 学習 / 読書 / 作品インプット(映画・ドラマ・マンガ)
├─ 創造・仕事 : 制作・コーディング / ディープワーク / 発信
├─ 関係資本   : 家族 / 友人・人脈
└─ 経済資本   : 家計 / 投資・資産
核(=目的)   : Compass(Layer 0、木の上)
外部入力(対象外): 天気・気圧 → 身体資本/精神状態 に作用(modifier)
```

## 3. データモデル

- `Goal`(新): id, title, horizon(期限ラベル), capital_weights(JSON {capital: weight}),
  metric(任意), target(任意), active(bool), created_at。フェーズ1は seed の founder 目標 1 件。
- `DomainWeight`(既存): 手動上書き用。capital キーで再利用。
- 達成度は基本オンザフライ計算。履歴は既存 `ExternalDomainEntry` / 各種テーブルを利用。

## 4. 算出ロジック(`scoring/life/tree.py`、純関数中心)

- 各 capital の達成度(0-100)を、最良の既存シグナルから算出:
  - 身体資本 = 既存 `domains.health_achievement`(6サブ達成度平均)
  - 精神状態 = garden 内省系(meditation/journaling/reflection)直近14日の頻度達成度
  - 知的資本 = garden(reading/learning)+ 学習進捗 の頻度達成度
  - 創造・仕事 = GitHub 直近14日のコミット活動日 + garden(creative/deepwork)頻度
  - 関係資本 = garden(social/family)頻度達成度
  - 経済資本 = garden(finance)頻度達成度
  - 核 = Compass `build_gap_report` の overall proximity
- 頻度達成度: 直近 N 日で当該行動が観測された日数 / 目標日数 → `upper_achievement`。
- **focus weight**: active Goal の capital_weights を基本に、DomainWeight 手動上書き、未指定は 1.0。
- **life_score** = Σ(weight×achievement)/Σweight(null capital は除外)。
- **floor breach**: capital 達成度 < floor(config `life_capital_floors`)なら breach。重点と無関係に警告。
- 純関数 `aggregate_tree(leaf_or_capital_achievements, weights, floors) -> {...}` を単体テスト。

葉(leaf)単位の達成度は **フェーズ2**。フェーズ1は capital 単位の達成度 + 葉はラベル表示。

## 5. API(`api/life.py` を拡張)

- `GET /api/life/tree` →
  ```
  {
    purpose: { overall, layers, archetype_name },     # Compass 要約
    goal: { title, horizon, capital_weights } | null, # active goal
    capitals: [{ key, label, achievement, weight, floor, breach, leaves: [label...] }],
    life_score, focus_capital, breaches: [capital_key...],
    generated_at
  }
  ```
- 既存 `GET /api/life` / weights / preset はフェーズ1では温存(後で統合)。

## 6. フロント(`pages/Life.tsx`, `#life`)

- 縦に 4 層を見せる: 目的(Compass 要約・タップで #identity)→ 目標(active goal)→
  ドメイン木(capital ごとに達成度バー + 重点ハイライト + フロア割れ警告)→ life_score。
- BottomNav に「人生」を追加。
- cockpit トークンで統一。Home への昇格(home=Life)は見てから判断(フェーズ後半)。

## 7. テスト

- `aggregate_tree` と頻度達成度を純関数で単体テスト。
- `/api/life/tree` の形状テスト(app_client)。
- 既存スイートが落ちないこと。

## 8. フェーズ分解(全面リニューアル)

- **フェーズ1(本spec で実装)**: ドメイン木 + life_score + focus + floor + 目標(seed)+ Life ビュー。
- フェーズ2: 葉単位の達成度 / 目標 CRUD UI / 作品(Compass)・栄養の取り込み。
- フェーズ3: Life を home に昇格、IA 全面再編、リネーム(healthcare→?)。
- フェーズ4: 相互関係(辺)の可視化・「今日の最適配分」提案の高度化。

## 9. YAGNI(フェーズ1で やらない)

- 葉単位の細かい達成度、目標の CRUD UI、相互関係グラフ、リネーム、home 置換。
