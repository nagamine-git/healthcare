# 個人差ファクター設定 UI 設計

日付: 2026-06-16
状態: 承認済み（推奨案でデプロイまで実施）

## 目的

身長・性別だけでなく、アプリの計算・判断に**実際に効く**個人差因子を科学的・医学的に
網羅し、専用「設定」タブから編集できるようにする。env デフォルトを UI 上書きでマージする
既存の `UserProfile` + `resolve_profile()` 流儀を延長する。

非目標: 計算に未接続の「飾り設定」は作らない。学習で決まる値（片頭痛トリガー・睡眠
ドライバー）は手入力対象にしない（手入力は精度を下げる）。**活動量レベル係数は入れない**
（TDEE は既に Garmin 実測 active_kcal から算出しており、推定係数は精度を落とすため）。

## アーキテクチャ（採用案 A）

`UserProfile`（単一行 id=1）に型付きカラムを追加。`resolve_profile()` がフィールド単位で
env デフォルトにフォールバック。派生値（有効半減期・目標 mg/kg・最大心拍）は resolve 層で計算。
スキーマ追加は既存の `_apply_lightweight_migrations()`（ALTER ADD COLUMN）で対応。

## 因子カタログ（計算直結のみ）

| グループ | 因子 | 保存カラム | 効く計算 | 入力 |
|---|---|---|---|---|
| 身体 | 年齢 | `age` | BMR(Mifflin)・最大心拍・(LLM) | 数値 |
| 身体 | 身長/性別/目標体重/体脂肪率/許容 | 既存 | 体組成・BMI・FFMI・BMR | 既存グリッド |
| 心拍 | 安静時心拍 | `resting_hr` | Karvonen 心拍ゾーン | 数値(上書き) |
| 心拍 | 最大心拍 | `max_hr` | 心拍ゾーン上限 | 数値(実測上書き)/式 |
| カフェイン | 喫煙 | `caffeine_smoker` | 消失半減期 ×0.6 | トグル |
| カフェイン | 経口避妊薬 | `caffeine_oral_contraceptives` | 消失半減期 ×1.8 | トグル(女性) |
| カフェイン | 妊娠中 | `caffeine_pregnant` | 消失半減期 ×2.6 | トグル(女性) |
| カフェイン | 感受性 | `caffeine_sensitivity` | 目標 mg/kg (high0.5/normal1.0/low1.5) | 3段階 |
| カフェイン | 半減期 手動上書き | `caffeine_half_life_override_h` | PK 全体(2–12h) | 数値(上級) |
| 睡眠 | 起床時刻 | `wake_time` | 就寝逆算・サーカディアン | 時刻 |
| 睡眠 | 必要睡眠量 | `sleep_need_min` | 睡眠不足判定 | 数値 |
| 睡眠 | クロノタイプ | `chronotype` | 睡眠/光曝露アドバイス(LLM) | 朝/中間/夜型 |
| 栄養 | タンパク質 g/kg | `protein_g_per_kg` | タンパク目標 | 数値 |
| 栄養 | 水分 mL/kg | `water_ml_per_kg` | 水分目標・ペース予測 | 数値 |

### 派生値（resolve 層）

- `caffeine_half_life_h` = override があればそれ、無ければ `base(5h) × (喫煙?0.6) × (OC?1.8) × (妊娠?2.6)`、[2,12]h にクランプ
- `caffeine_target_mg_per_kg` = 感受性 → {high:0.5, normal:1.0, low:1.5}
- `max_hr` = override、無ければ Tanaka 208 − 0.7×age
- `resting_hr` = override、無ければ config

## API

- `GET /api/settings` … 全解決値 + 派生値 + フィールド毎 source を返す
- `PUT /api/settings` … 任意サブセットを部分更新（全フィールド optional）。保存後に当日再計算
- 物理体型（体重/体脂肪グリッド）は既存 `PUT /api/profile`（assess 安全ゲート付き）を継続使用

バリデーション: age 10–100 / resting_hr 30–120 / max_hr 120–220 / sleep_need_min 240–660 /
half_life_override 2–12 / protein 0.5–3.0 / water 20–60。範囲外は 422。

## 計算への接続（settings.X → resolve_profile().X へ置換）

- カフェイン半減期: `dashboard.py` / `llm/client.py` / `timeline.py`
- カフェイン目標 mg/kg: `dashboard.py` / `llm/client.py`
- 年齢: `nutrition.py`(BMR) / `prompts.py`(Karvonen, 表示)
- 安静時/最大心拍: `prompts.py` `_karvonen_zones`
- 起床/必要睡眠: `sleep_plan.py` / `dashboard.py` / `llm/client.py` / `timeline.py`
- タンパク質/水分 per kg: `nutrition.py`
- クロノタイプ: `prompts.py`（睡眠コンテキスト）

## UI

専用「設定」タブ（`Today.tsx` の Tab に `settings` 追加）。グループ別の開閉式セクション
（身体 / 心拍 / カフェイン / 睡眠 / 栄養）。トグルスイッチ・数値・3段階セグメント。
各設定に「効く計算」の一言ヒントと、派生値（有効半減期・最大心拍など）のライブ表示。
既存 `PhysiqueTargetSection` は設定タブの身体グループへ移設。アイコン付き・開閉式
（ui-prefs に準拠）。OC/妊娠トグルは性別=女性のときのみ表示。

## テスト

- resolve 層の派生（半減期クランプ・感受性マップ・max_hr フォールバック）の単体テスト
- `PUT /api/settings` の部分更新・バリデーション境界の API テスト
- カフェイン/栄養/睡眠の各消費が resolve 値を反映するスモーク
- 既存 367 テストを壊さない

## デプロイ

backend 再ビルド + frontend 再ビルド（新タブのため front 変更あり）。`op` サインイン済みなら
既存 `.env.runtime` 再利用で `up -d --build backend frontend`。PWA はリロード2回で反映。
