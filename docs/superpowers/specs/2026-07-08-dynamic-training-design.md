# 動的トレーニング提案 (器具DB / 実績ベース負荷 / 天気連動 / 片頭痛強度分岐)

## 背景 (2026-07-08 実測)

- 7/8 朝の助言が「片頭痛継続中→休養最優先」(朝BB89なのにボックスブレシングのみ)。
  実態: 強度2(軽度)のエピソードが生成時(06:30)に開いていて07:43に終了。
  ①強度を無視して全面休養 ②終了後も助言が古いまま、の2バグ。
- 棚卸しで確認したハードコード: 器具(config.user_equipment)・種目・開始重量(user_starting_weights)、
  負荷漸進はLLMの目視任せ、天気(降水確率/気温/湿度)は取得済みだが助言に未連携、WBGT無し。

## 実装

1. **片頭痛の強度分岐** (prompts.py): sev≥6=休養 / 4-5=軽運動可 / **≤3=通常提案(HIITのみ回避)**。
   終了済みエピソードは制約にしない。
2. **エピソード終了で助言を自動再生成** (api/migraine.py end): 当日助言がエピソード中に生成されて
   いれば background で generate_advice_for_date を再実行 (fire-and-forget, 失敗は無視)。
3. **天気連動** — scoring/weather_risk.py (純関数): Stull近似の湿球温度→簡易WBGT(放射無し
   0.7Tw+0.3Ta)→熱中症レベル(安全/注意/警戒/厳重警戒/危険)。get_weather_forecast の hourly から
   直近18hの {時刻, 気温, 降水確率, 熱レベル} と rain/heat フラグに要約 → payload["weather_today"]。
   prompts: 屋外有酸素(ラン/ラッキング)は降水確率≥50%の時間帯回避・厳重警戒以上は屋外高強度禁止、
   最適時間帯と根拠を添えて提案。
4. **器具DB** — EquipmentItem(name, available, note, sort)。空なら settings.user_equipment から
   自動シード。GET/POST/DELETE /api/equipment。prompts の {equipment} は DB(available)優先・
   settingsフォールバック (scoring/equipment.py: resolve_equipment)。SettingsTab に器具セクション。
5. **実績ベース負荷** — scoring/training_load.py:
   - Workout.raw_json (summarizedExerciseSets: category/weight/reps) と直近処方 (LlmComment
     exercises) から種目別の直近実績を構築。
   - suggest: double progression (同重量で目標rep×2セッション→次の手持ち重量へ) + 7日超空白は
     -10〜20% deload + 実績なしは settings.user_starting_weights × training_level 係数
     (beginner 1.0 / intermediate 1.25 / advanced 1.5)。手持ち重量は [2,4,8,12,16,20]。
   - payload["load_suggestions"]。prompts: 「重量はシステム算出の suggested を基準に採用」。
   - settings.training_level (personal target, env override) を新設。

## テスト

weather_risk 純関数 / training_load 純関数 (漸進・deload・初回) / equipment API (seed/upsert/一覧)。

## 非目標

種目マスタのDB化 (config据え置き)。1RM推定。WBGT の放射項 (球黒温度なしの近似で開始)。
profile UI での training_level 編集 (env で開始)。
