# メトリクス・アトラス(全体マップ)設計

## 目的
サービス内に散らばった指標を、`総合点 → ドメイン → 個別指標` の構造ツリーに集約し、
各リーフを **現状 / 世の中 / 目標** の統一 UI で並べる。第3階層以下はプルダウン開閉。

## 位置づけ(確定)
**B: 既存タブはそのまま残し、俯瞰用の新タブ「全体」を1つ足す**。詳細は各タブへドリルダウン
(将来主役化を判断)。デフォルトタブは従来どおり総合。

## ノード構造
```
総合点(total, target=100)
├ 睡眠 (sleep_sub)        ├ 自律神経 (hrv_sub)
├ エネルギー (bb_sub)     ├ 運動負荷 (load_sub)
├ 体型 ─ 体重 / 体脂肪率 / FFMI / BMI / 骨格筋量 / 内臓脂肪 / 基礎代謝
├ 体力 ─ 腕立て / 椅子立ち上がり / 握力 / SRT
└ 健康診断 ─ (健診項目: BMI/血圧/脂質/血糖/肝/腎/尿酸/Hb …)
```

## リーフのデータモデル
```python
{
  "key": str, "label": str, "unit": str,
  "direction": "up" | "down" | "band" | "none",  # 高い/低い/帯/方向なし(色分け用)
  "current": float | None,                       # 現状(最新値)
  "population": {"median": x} | {"percentile": p} | {"range": [lo, hi]} | None,  # 世の中
  "target": float | None,                        # 目標
  "children": [...],                             # 枝のみ
}
```
- 三値が揃わないのは前提。欠損は UI で「—」。行は隠さない(現状だけでも意味がある)。
- 「世の中」列は指標で型が違う: 中央値(体型/VO2max norms)・percentile(体力テスト)・
  基準範囲(健診)を `population` に型付きで持ち、フロントが出し分ける。

## データ源(再利用)
- 現状: 最新 `DailyScore`(total + *_sub)、`WeightSample`、`BodyCompositionSample`、
  `FitnessTestResult`、最新 `HealthCheckup.values`。
- 世の中: `population_norms.norm_for()`(中央値=mean)、`fitness_test` percentile、
  `checkup_items` の基準範囲。
- 目標: `UserProfile` / `config`(target_weight_kg, target_body_fat_pct, target_sleep_min 等)。

## 構成
- backend `scoring/atlas.py`: `build_atlas(session) -> dict`(純粋寄り、上記を集約)。
- backend `api/atlas.py`: `GET /api/atlas`。main.py に登録。
- frontend `AtlasTree.tsx`: 入れ子の開閉ツリー。各リーフ = ラベル + 現状/世の中/目標 の3列 +
  目標との距離を示す細バー。第3階層以下は既定で畳む。`Today.tsx` に新タブ「全体」。

## エラー処理 / テスト
- データ無しのリーフは current=None → 「—」。スコア未計算でも 500 にしない。
- テスト: `build_atlas` が空 DB で例外を出さない / 体重・体脂肪を入れると体型リーフに
  現状・中央値・目標が乗る / 健診項目が基準範囲付きで出る。

## 非目標(v1 では作らない)
- 人生ツリー(人生タブ)との統合(別ルート。重複させない)。
- リーフからの自動ドリルダウン遷移(将来)。トレンドの再描画(既存タブが担う)。
