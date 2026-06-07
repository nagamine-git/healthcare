# Garmin 全データ活用: 抽出・科学的分析・可視化

日付: 2026-06-07 / 依頼: 「取れるデータは全てとって、科学的医学的に分析して、ダッシュボードで可視化」

## 背景

調査の結果、(A) sleep_session.raw_json に保存済みだが未活用のフィールド群、
(B) python-garminconnect で取得可能だが未取得の API 群があることを実機 (Instinct 3) で確認した。

## A. sleep raw_json からの抽出 (`app/ingest/sleep_extras.py`)

スキーマ変更を避けるため、全て `metric_sample` (source="garmin", ts=対象日 07:00 naive) に書く。
sync 時に毎回抽出 + 過去分は一括バックフィル (`backfill_sleep_extras()`)。

| metric_key | 元フィールド | 単位 | 医学的意義 |
|---|---|---|---|
| sleep_spo2_avg | dto.averageSpO2Value | % | 睡眠時平均血中酸素。<94% は低酸素傾向 |
| sleep_spo2_lowest | dto.lowestSpO2Value | % | 無呼吸スクリーニング。<80% は要注目 |
| sleep_respiration_avg | dto.averageRespirationValue | brpm | 安静呼吸数。ベースライン+2 以上は体調変化サイン |
| sleep_stress_avg | dto.avgSleepStress | level | 睡眠中の自律神経負荷 |
| sleep_resting_hr | raw.restingHeartRate | bpm | 夜間安静時心拍。上昇トレンドは回復不全/疾病前兆 |
| sleep_restless_moments | raw.restlessMomentsCount | count | 中途覚醒の代理指標 |
| sleep_bb_change | raw.bodyBatteryChange | pt | 睡眠での回復量 |
| sleep_nap_min | dto.napTimeSeconds/60 | min | 昼寝 |
| sleep_midpoint_hour | (start+end)/2 のローカル時刻 | 時 | 睡眠中点。概日リズムの標準指標 (Roenneberg)。ブレ=社会的時差ボケ |
| sleep_breath_disruption | dto.breathingDisruptionSeverity を 0/1/2 (LOW/MODERATE/HIGH) | level | 呼吸乱れ |

raw_json は再保存しない (元の sleep_session に既にある)。値が無い項目はスキップ。

## B. 新規 Garmin API 取得 (garmin_client + garmin_sync)

| metric_key | API | value | raw_json |
|---|---|---|---|
| training_readiness | get_training_readiness | score (0-100) | level / feedbackShort / 要因分解 (sleepScoreFactorPercent 等) |
| fitness_age | get_fitnessage_data | fitnessAge | chronologicalAge / achievableFitnessAge / components |
| respiration_waking_avg | get_respiration_data | avgWakingRespirationValue | なし |
| floors_up | get_floors | 日次合計 (フィールドが無い場合スキップ) | なし |

全て日次 1 サンプル、ts=対象日 07:00。API エラーは既存方針通り握りつぶして他を継続。

## C. 科学的分析

### 達成度関数 (achievement.py)

- `spo2_achievement(avg)` = upper(avg, 90, 95)。SpO2 ≥95% が正常域 (成人)。
- `respiration_achievement(avg)` = band(avg, 12, 18, softness 3)。成人安静時 12-20brpm。
- `readiness_achievement(score)` = score そのまま (Garmin が 0-100 合成済み)。
- `sleep_regularity_achievement(sd_hour)` = 中点の 14 日 SD。SD ≤0.5h で 100、線形に 2.0h で 0。
  (睡眠規則性は死亡リスク・気分障害と独立相関: Windred 2024, Sleep Regularity Index 系研究)

### wellbeing アラート追加 (wellbeing_alerts.py)

| code | 条件 (保守的) | severity | 根拠 |
|---|---|---|---|
| sleep_spo2_low | 直近 3 日中 2 日 avg<93% または lowest<80% | warning | 手首式は誤検出が多いため単発では出さない。継続時のみ受診提案 |
| respiration_elevated | 直近 3 日平均が 28 日 baseline +2brpm 以上 | info | 安静呼吸数上昇は感染症・過労の早期サイン (Shapiro 2021 等) |
| readiness_low_streak | training_readiness <30 が 3 日連続 | warning | 回復日推奨 |
| sleep_irregular | 中点 14 日 SD >1.5h | info | 概日リズム乱れ。偏頭痛トリガーにも (規則睡眠は頭痛予防の一次推奨) |

医学的免責: アラートは「受診や注意のきっかけ」であり診断ではない文言にする。

### LLM payload (llm/client.py + prompts.py)

today payload に `physio` ブロック:
spo2 (avg/lowest), respiration, sleep_midpoint + 規則性 SD, readiness (score/level/feedback/要因分解),
fitness_age, bb_change, restless, nap。prompt に「readiness が低い日は回復系の配分を優先」等の指針を追記。

## D. 可視化 (/api/trends + TrendsSection)

新トレンドカード (既存 6 + 5 = 11):

| key | label | ideal | 単位 |
|---|---|---|---|
| readiness | 攻め時 (Readiness) | upper good=70 | 点 |
| spo2 | 血中酸素 (睡眠) | band 94-100 | % |
| respiration | 呼吸数 (睡眠) | band 12-18 | brpm |
| rhr_night | 夜間心拍 | band 40-55 (低いほど良いが下限あり) | bpm |
| sleep_midpoint | 睡眠中点 | band 個人中央値±0.75h | 時 |

各カードに API 側から `subtitle` (例: spo2 → "最低 72%") を返し、TrendCard の hint と統合。
バックエンドの series 取得は metric_sample から日次 (JST) で引く汎用関数を trend_sources に追加。

## テスト

- sleep_extras: 実 raw_json 形のフィクスチャから全キー抽出・欠損スキップ・中点計算 (跨ぎ夜)
- sync: フェイク API で readiness/fitness_age/respiration の MetricSample 書き込み
- achievement: 新関数の境界値
- alerts: 各ルールの発火/非発火
- trends API: 新 5 metric がレスポンスに含まれ ideal/subtitle が正しい
