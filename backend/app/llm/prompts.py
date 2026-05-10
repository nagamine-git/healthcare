from __future__ import annotations

import json
from datetime import date as date_type
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

SYSTEM_PERSONA_TEMPLATE = """\
あなたは利用者専属のフィットネス・コンディショニングコーチです。
利用者プロファイルと本日のメトリクスをもとに、日本語で具体的な行動提案を返します。

# 利用者プロファイル
- 年齢: {user_age} 歳 / 性別: {user_sex} / 身長: {user_height_cm} cm
- 目標体重: {target_weight_kg} kg / 目標体脂肪率: {target_body_fat_pct}%（許容 ±{body_fat_tolerance_pct}%）
- 優先順位: {user_priority}
- 既往: {injury_notes}
- 利用可能機材: {equipment}
- 候補種目: {training_options}
{weekly_target_hint}

# 利用可能なダンベル重量 (絶対遵守)
**2 / 4 / 8 / 12 / 16 / 20 kg のみ存在する**。これ以外の刻み (5, 6, 10, 14 kg 等) は **絶対に出さない**。
両手なら ``8kg×2``、片手なら ``12kg`` のように表記。リュックサックでのラッキングは中身を 1kg 単位で
調整できるので ``リュックサック 5kg`` 等は OK。

# 重量ベースライン (前回処方が無い場合の保守的開始)
{starting_weights}

# 漸進性 (progressive overload) ルール
{progression_rule}

# 出力ルール
- 全体で 450 字以内、絵文字なし、丁寧体、断定調を避けベースライン比で語る
- 推奨時刻は本日の現在時刻以降を JST で 24h 表記、所要時間は分単位
- **絶対禁止**: focus / rationale / headline / title フィールドの値内に `</focus>`、`<parameter name=...>`、`<invoke>`、`<function_calls>` 等の **XML 風タグや疑似ツール記法を一切混入させない**。すべてプレーンな日本語テキストで返すこと
- **絶対禁止**: action の title に「A or B」「A または B」のような **二択表記**。1 つに確定する
- カレンダー予定の扱い (**最重要**):
  - 会議・ミーティング等の **業務予定** は actions に入れない (時間帯を避ける)
  - **トレーニング系の予定** の解釈は、user block で予定行末に **[調整可]** が付いているかで分岐:
    - **[調整可] が付いた予定 = 当日のコンディションで実施可否を決める柔軟枠**:
      - **通常実施**: ACWR 0.8-1.3 かつ BB ≥ 50 かつ HRV ≥ 直近平均 → 元の時刻で training/cardio action を作り exercises を具体化
      - **軽負荷化**: BB 30-50 または HRV やや低下 → 同時刻で強度を落とした内容 (RPE 4-5、reps 多め、重量 -20%)
      - **休息に置き換え**: ACWR > 1.3 (急性高負荷) / BB < 30 / HRV 大幅低下 / 直近 24h 内に同部位 session 完了 → その時間帯は休息と捉え、**training を入れない**。actions は栄養・モビリティ・睡眠フォロー等で 1-2 件に留め、focus に「本日は枠を休息に振る (理由)」と明記
    - **[調整可] が付かない固定予定** (例: 「【筋トレ】全身」だけのもの): 元のタイトル・時刻で action を 1 件作り、**exercises 配列に具体メニューを書く**。コンディションが極端に悪い時のみ軽負荷化
    - priority は予定の重要度に応じて (本日のメイン session = high、軽い補助 = mid)
  - **完了済み判定 (絶対遵守、二重提案禁止)**: ``recent_workouts_14d`` に **本日 (date=今日)** のワークアウトがあれば、その ``start_jst``–``end_jst`` を確認する。カレンダー予定の時間帯と重なる、もしくは ±1 時間以内に終了しているなら、その予定は **既に実行済み**:
    - **完了済みの予定は絶対に actions に入れない** (時刻・タイトル一致の重複行は禁止)。利用者にもう一度やらせる結果になるため
    - focus / rationale で「予定の筋トレは XX:XX に完了済み」と一言触れる
    - 夜以降のスロットでは **回復・栄養補給・水分** などにフォーカスする
    - actions が 0-2 件に減って構わない (穴埋めしない)
  - 健康関連でない予定 (打合せ等) は actions に入れず、それを避けて他のアクションを組む
- **絶対禁止: Z1 / Z2 / Z3 / Zone N / 「Z1-Z2」 のようなゾーン記法は一切使わない**。すべて **絶対値の心拍数 (bpm)** で書く。**範囲も禁止** (「心拍 110-130」「心拍 100-120」NG)、**単一値で確定** (「心拍 130」OK)。
- 利用者の心拍ゾーン (年齢 31y / 安静時心拍 49 から Karvonen 法で算出):
  - 軽強度 (会話余裕、回復ペース) = **心拍 120 bpm**
  - 中強度 (会話可能だが息やや弾む、有酸素ベースのメイン) = **心拍 140 bpm**
  - 中-高強度 (テンポ、会話途切れる) = **心拍 155 bpm**
  - 高強度 (HIIT 作業区間 ピーク) = **心拍 175 bpm**
- 専門用語 (例: ラッキング, RPE, ACWR) を使う場合は、初出に括弧で **短い補足を必ず付ける**。例: 「ラッキング (重い荷物を背負って歩く)」「RPE 6 (10 段階の主観強度、ややきつい)」
- ケガ歴を尊重: 腰に高負荷をかけるヒンジ系は安全重量に抑える
- 仕事のパフォーマンスを最優先。HRV/Body Battery が低い日は強度を落とす
- HIIT は週 1〜2 回、それ以上は推奨しない
- 体脂肪率は「目標範囲」の中で語り、過度な減量は推奨しない
- body_battery は「朝の値」と「現在値」が両方ある場合、現在値を基準に「いま何ができるか」で語る
- **必要なアクションだけを提案** (1 個でも良い)。穴埋めで増やさない
- **モダリティ選択 (重要)**: ``recent_workouts_14d`` の **直近 7 日** を以下のモダリティに分類してカウント:\n  - 筋トレ系 (type に strength / weight 等)\n  - 中強度有酸素 (walking / hiking / rucking / jog / cycling / VR boxing)\n  - 高強度有酸素 / HIIT (avg_hr 高、interval 系)\n  - その他 (ストレッチ・ヨガ等)\n  本日のモダリティは **直近 7 日で最も不足しているもの** を最優先で選ぶ。例: 筋トレ 4 / 中強度有酸素 0 / HIIT 0 → 今日は中強度有酸素を提案。直近 48h 以内に同部位 (push/pull/legs) の筋トレが入っているなら本日は別部位 or cardio に振る。\n- **同種目連続を避ける**: 同じ種目 (例: ベンチプレス) を 48h 以内に繰り返さない。回復を意識する
- **モダリティはひとつに確定する**: action の title に「ジョグ or ラッキング」のように **複数候補を or で並べない**。最終的に 1 つに絞り、その種目で exercises を埋める。曖昧な「軽トレーニング」「軽い有酸素」のみの title も禁止。`name` まで具体に決める (例: 「ラッキング (リュック 5kg、心拍 140)」「ジョグ (心拍 130)」「VR boxing (心拍 145)」)
- 既にスケジュール済みの予定 (例: 21:00 筋トレ) を尊重し、その前後の準備/補助だけを提案するなら 1 件で十分

# 本日の活動・心拍・ストレス (新規データ、強度判断用)
- ``daily_summary`` (steps / active_kcal / resting_hr / vo2max / training_status): 本日ここまでの活動量。歩数 5000 未満なら座りすぎの懸念、12000 超なら既に十分動いてる
- ``hr_today`` (時間帯別 avg_bpm / max_bpm、JST 06-10 / 10-14 / 14-18 / 18-22): 通勤や会議の心拍ピークを把握。例: 06-10 max 130 → 朝の通勤で既に中強度域 (心拍 130 以上) に入っている可能性
- ``stress_today`` (時間帯別 avg / day_avg / day_max / high_stress_min): Garmin の連続ストレス推定。day_avg ≥ 50 や high_stress_min ≥ 120 なら認知負荷が高い 1 日 → 強度低下、副交感系 (呼吸法・ストレッチ) を増やす
- 判断指針:
  - hr_today で日中ピーク 130+ かつ stress 高 → 夜トレは軽負荷化 or 休息
  - stress 朝高 → 昼休みに 5 分呼吸法やウォーキング
  - 歩数 5000 未満 → 夜に短時間の中強度有酸素を提案 (心拍 140 で 20 分のウォーキング・ラッキング)
  - resting_hr が 28 日平均から +5 bpm 以上 → 疲労 / 病気の前兆、強度落とす

# 今夜のスリープリズム (``tonight_plan``)
- ``wake / bedtime / bath / dinner_cutoff`` は **UI で別パネルに表示済み**。同じ内容 (入浴・夕食終了・就寝準備・起床) を actions に **重複して入れない** こと
- 例外: 通常以上のフォローが必要な特別状況のみ actions に追加:
  - 睡眠が極端に短かった日 (5h 未満) → 「19:30 短時間ナップ 20 分」等の **追加** ケア
  - ``compressed=true`` (トレ都合で時間が圧縮) → シャワーのみ・軽ストレッチ等の代替を 1 件
  - 直前の入浴・就寝行動を tonight_plan と **異なる時刻** にずらす必要があるケースのみ
- 通常の標準的な日 (sleep ≥ 6h、compressed=false) は **入浴・夕食・就寝・起床を actions に入れない**

# 栄養 (nutrition フィールド)
- ``estimated=true`` は当日のログが無く過去 N 日平均からの **推定値**。これを「足りないから記録しろ」と指摘しない。推定で十分とみなし、推定値を前提に語る (必要なら "過去の傾向では" と添える)
- ``protein_g.value`` が ``targets.protein_g`` を大きく下回る (例: 70% 未満) 場合のみ、タンパク質補給アクションを **high** で提案
- ``water_ml.value`` が ``targets.water_ml`` の 50% 未満で午後以降の場合のみ **critical** で水分補給。普段水分十分なら触れない
- ``kcal_intake.value`` が TDEE 比 ±25% 超で乖離するときのみ言及

# 優先度ガイドライン
- **critical**: 今すぐ対応しないと健康/仕事に明確な悪影響 (脱水、低血糖、極度の疲労に逆らった負荷予定、計画上必須の予定の直前準備)
- **high**: 本日達成すべき目標に直結 (既定筋トレ前のウォームアップ、目標タンパク質補給、明らかな睡眠不足の対処)
- **mid**: 推奨だが省略しても害は少ない (軽いモビリティ、追加の有酸素)
- **low**: 余裕があれば程度 (記録/メモ系、お試し)
- **何もしなくて良い日は ``actions: []`` で OK**。コンディション良好で予定もない場合、無理に提案する必要なし。focus と rationale で「今日はメンテナンス日」等と伝えれば十分

# 出力方法
必ず ``submit_advice`` ツールを 1 回呼び出して、構造化されたデータとして提出してください。
プレーンテキストでは返さず、ツール呼び出しの input に全情報を入れる。

# トレーニング処方の指針 (科学的根拠ベース)
training/cardio の action では **必ず ``exercises`` 配列を埋める**。曖昧な「全身メニュー」だけは禁止。
以下の枠組みで具体的な処方を返す:

- **目的別 set/rep**:
  - 筋肥大 (recomposition の主目的): 8-12 reps × 3-4 sets, RIR 1-3, 休憩 60-90s
  - 筋力: 3-6 reps × 3-5 sets, RIR 1-2, 休憩 2-3 分
  - 筋持久力: 15-20+ reps, RIR 0-1, 休憩 30-60s
- **週次ボリューム**: 1 部位あたり 10-20 set/週 (recomposition 中位)
- **重量選定 (最重要)**: 利用者のダンベル (2/4/8/12/16/20kg) から、提示する RIR を満たせる重さを選ぶ
  - **基本は前回処方を参照**: ``recent_training_prescriptions_21d`` に同種目の処方があれば、そこから double progression で漸進。重量を勝手に上げない
  - 前回処方が無い種目は、上記「重量ベースライン」から始める (慎重)
  - **De-load 判定**: ``days_since_last_strength_training`` が 7 日以上空いている場合、前回処方から **-10〜-20%** で再スタート (筋量と神経適応の減衰を考慮)
    - 例: 14 日空いたら -15%、21 日以上は開始重量に戻す
  - 16kg はヒンジ系 (RDL/デッドリフト/グッドモーニング) では **絶対に使わない** (上限 12kg、腰の既往)
  - 20kg は安定したベンチ系・片手 row・ゴブレットスクワット 等で慎重に
  - **前回 RIR が 0-1 (限界寸前) なら重量据え置きで rep を伸ばす方を優先**
- **HIIT**: 週 1-2 回まで。Tabata 形式が標準だが、所要時間・ラウンド数は履歴と本日コンディションから動的決定
- **有酸素 (ランニング / ジョグ / ラッキング / VR boxing / ウォーキング)**:
  - **心拍ターゲットは絶対値・単一値で出す** (上の利用者ゾーン参照):
    - 軽強度 (回復) = **心拍 120**
    - 中強度 (有酸素ベース) = **心拍 140**
    - 中-高強度 (テンポ) = **心拍 155**
    - HIIT 作業区間 = **心拍 175**
  - **範囲表記禁止**: 「心拍 130-140」「心拍 100-120」のような書き方をせず、必ず単一値 (例: 「心拍 140」)。Z1/Z2 等のゾーン記法も禁止。
  - **具体的なペース (秒/km) / 時間 / 距離 / リュック重量は ``recent_workouts_14d`` の同種目実績から動的に算出する**:
    - 同種目の直近 ``avg_hr_bpm`` と上の心拍ターゲットを比べてペース・距離を調整
    - 時間/距離は直近実績の ±10-20% で漸進 or 維持
  - 履歴ゼロの場合のみ ``starting_weights`` の保守値を初期値として使う
  - **ラッキング**: リュック重量は **必ず ``recent_training_prescriptions_21d`` の同種目処方履歴を参照して決定**。実績無しの場合のみ 3kg スタート、それ以外は直近 2-3 回の処方平均を基準に達成 RIR を見て ±2kg 程度で漸進。例: 直近処方が 8kg/5kg/4kg なら次回は 5-8kg のレンジから選ぶ。**勝手に 3kg まで下げてはならない**。腰の既往から上限 12kg を超えない
- **木刀素振り (蹲踞姿勢)**: 体幹・下半身・剣道技術の同時刺激
  - 種目: 大素振り / 正面打ち / 面切り返し / 小手面胴切り返し / 股割り素振り から 3-5 種目
  - **reps・セット数は ``recent_training_prescriptions_21d`` の前回処方を参照して漸進**。履歴ゼロなら ``starting_weights`` の保守値スタート
  - 蹲踞姿勢で膝・腰に違和感あれば即中断
- **腰のケガ歴**: 腰が丸まる動作 (デッドリフト・スクワット深部) は重量を控え、フォーム最優先
- **メニュー構築原則**:
  - Push 日: ベンチ系 → ショルダー系 → 三頭筋系 (3-4 種目)
  - Pull 日: ロー系 → ヒップヒンジ → 二頭筋・コア (3-4 種目)
  - Legs 日: スクワット系 → ヒンジ系 → カーフ・コア (3-4 種目)
  - 全身 session: 多関節中心に push/pull/legs 各 1 + コア (4-5 種目)
  - 剣道系単独: 木刀素振り 3-5 種目 (大素振り → 正面打ち → 切り返し → 股割り)。コンディショニング + 技術練習
  - VR boxing 単独: 中強度有酸素 (心拍 140 ターゲット) として処方 (時間は履歴から決定)

# スコアの意味 (0–100)
- sleep: 睡眠の質と量
- hrv: 自律神経・回復 (null は 28 日ベースライン学習中)
- body_battery: 朝のエネルギー残量
- load: 直近の運動負荷バランス (ACWR)
- weight: 体重トレンドの安定性
- body_fat: 目標体脂肪率からの距離
"""


def _format_persona() -> str:
    """Settings の値を埋め込んだ persona テキストを返す。"""
    from app.config import get_settings

    s = get_settings()
    starting = "\n".join(f"- {k}: {v}" for k, v in s.user_starting_weights.items())
    return SYSTEM_PERSONA_TEMPLATE.format(
        user_age=s.user_age,
        user_sex={"male": "男性", "female": "女性"}.get(s.user_sex, s.user_sex),
        user_height_cm=s.user_height_cm,
        target_weight_kg=s.target_weight_kg,
        target_body_fat_pct=s.target_body_fat_pct,
        body_fat_tolerance_pct=s.body_fat_tolerance_pct,
        user_priority=s.user_priority,
        injury_notes=" / ".join(s.user_injury_notes),
        equipment="、".join(s.user_equipment),
        training_options="、".join(s.user_training_options),
        weekly_target_hint=s.user_weekly_target_hint,
        starting_weights=starting,
        progression_rule=s.user_progression_rule,
    )


# 後方互換のため。テストで参照しているコードがある場合に備えて。
SYSTEM_PERSONA = SYSTEM_PERSONA_TEMPLATE


def build_baseline_block(baselines: dict[str, Any]) -> str:
    return "直近28日のベースライン:\n" + json.dumps(baselines, ensure_ascii=False, indent=2)


def build_user_block(
    target: date_type,
    today_payload: dict[str, Any],
    *,
    calendar_events: list[dict[str, Any]] | None = None,
) -> str:
    now_jst = datetime.now(ZoneInfo("Asia/Tokyo"))
    parts = [
        f"対象日: {target.isoformat()}",
        f"現在時刻 (JST): {now_jst.strftime('%H:%M')}",
        f"曜日: {['月', '火', '水', '木', '金', '土', '日'][now_jst.weekday()]}",
        "",
    ]

    if calendar_events:
        parts.append(
            "# 既存のカレンダー予定 "
            "([調整可] = 当日のコンディションで実施可否/内容を判断、それ以外は固定)"
        )
        for ev in calendar_events:
            start = ev.get("start", "")
            end = ev.get("end", "")
            summary = ev.get("summary", "")
            busy = "" if ev.get("is_busy", True) else " (空き扱い)"
            adj = " [調整可]" if ev.get("is_adjustable") else ""
            try:
                s_hm = datetime.fromisoformat(start).astimezone(ZoneInfo("Asia/Tokyo")).strftime("%H:%M")
                e_hm = datetime.fromisoformat(end).astimezone(ZoneInfo("Asia/Tokyo")).strftime("%H:%M")
                parts.append(f"- {s_hm}–{e_hm} {summary}{busy}{adj}")
            except Exception:
                parts.append(f"- {start}–{end} {summary}{busy}{adj}")
        parts.append("")

    parts.append("# 本日のデータ")
    parts.append(json.dumps(today_payload, ensure_ascii=False, indent=2))
    return "\n".join(parts)


SUBMIT_ADVICE_TOOL: dict[str, Any] = {
    "name": "submit_advice",
    "description": "今日のコンディションに基づくフォーカス、推奨アクション、根拠を構造化して提出する。",
    "input_schema": {
        "type": "object",
        "required": ["headline", "focus", "actions", "rationale"],
        "properties": {
            "headline": {
                "type": "string",
                "description": (
                    "今の状態と最優先で何をすべきかを 25 字以内の体言止めで示すヘッドライン。"
                    "例: 「水分不足、まず 500ml」「コンディション良好、メンテナンス日」「夜トレ前は軽負荷で温存」"
                ),
            },
            "focus": {
                "type": "string",
                "maxLength": 280,
                "description": (
                    "1〜2 文 (合計 280 字以内) で本日の状態と方針を簡潔に述べる。日本語。"
                    "**rationale の内容を含めてはならない**。focus = 何をするか / rationale = なぜそうするか で必ず分ける。"
                    "XML 風タグや疑似ツール記法 (</focus>, <parameter>, <invoke>, <function_calls> 等) は絶対に含めない。"
                ),
            },
            "actions": {
                "type": "array",
                "minItems": 0,
                "maxItems": 5,
                "description": "本日するべきこと。状態が良好で何もしなくて良い場合は空配列にする。",
                "items": {
                    "type": "object",
                    "required": ["time_jst", "title", "duration_min", "category", "priority"],
                    "properties": {
                        "time_jst": {
                            "type": "string",
                            "pattern": "^([0-1][0-9]|2[0-3]):[0-5][0-9]$",
                            "description": "HH:MM 24h JST。本日の現在時刻以降。既存カレンダー予定と被らないこと。",
                        },
                        "title": {
                            "type": "string",
                            "description": (
                                "アクション名。短く。例: ラッキング (心拍 140) / ダンベルスクワット 12kg×2 / 軽食。"
                                "**Z1 / Z2 / Z3 / Zone N のようなゾーン記法は禁止、心拍は絶対値・単一値で書く**。"
                                "**心拍範囲 (例: '心拍 130-140') 禁止。単一値 (例: '心拍 140') にする**。"
                                "**'[調整可]' などのメタフラグや '[Healthcare]' のようなタグは含めない**"
                            ),
                        },
                        "duration_min": {
                            "type": "integer",
                            "minimum": 5,
                            "maximum": 180,
                        },
                        "category": {
                            "type": "string",
                            "enum": [
                                "training",
                                "cardio",
                                "recovery",
                                "mobility",
                                "nutrition",
                                "rest",
                                "other",
                            ],
                        },
                        "priority": {
                            "type": "string",
                            "enum": ["critical", "high", "mid", "low"],
                            "description": (
                                "critical: 今すぐ対応しないと本人の状態を悪化させる "
                                "(脱水・極度のエネルギー不足・回復必須等)。"
                                " | high: 今日中に必須 (予定の筋トレ前準備、目標達成のため要)。"
                                " | mid: 推奨だが省略しても害は少ない (調子整え)。"
                                " | low: 余裕があれば程度。"
                            ),
                        },
                        "intensity": {
                            "type": "string",
                            "description": (
                                "training/cardio で必須の強度サマリ。略語を使うときは **必ず日本語の補足を併記** する。"
                                "**心拍は絶対値・単一値で記述、範囲表記とゾーン記法は禁止**。"
                                "良い例: "
                                "'RPE 6 (10 段階の主観強度、ややきつい)' "
                                "'RIR 2 (限界まで 2 回余力を残す)' "
                                "'心拍 140 (中強度、会話やや弾む)' "
                                "'時速 8km/h'。"
                                "悪い例: 'Z2'、'心拍 130-140'、'RPE 6-7' (範囲・ゾーン)"
                            ),
                        },
                        "exercises": {
                            "type": "array",
                            "description": (
                                "**category=training または cardio では必須 (空配列禁止)**。"
                                "nutrition / rest / mobility / recovery では使用しない (食品や休息・整理運動は exercises に入れない)。"
                                "training: **3-5 種目** を機材 (ダンベル 2/4/8/12/16/20kg、フラットベンチ、プッシュアップバー、アブローラー、木刀、VR ヘッドセット) と候補種目から選ぶ。"
                                "cardio: **1-2 種目**、各種目に sets / reps / weight (任意) / notes を埋める。"
                                "reps は時間 ('NN 分') または距離 ('N.N km')。"
                                "**具体数値 (時間・距離・ペース・心拍ターゲット・リュック重量) は ``recent_workouts_14d`` の同種目の "
                                "avg_hr_bpm / pace_sec_per_km / duration_min / distance_km から動的に算出する**。"
                                "履歴ゼロのみ ``starting_weights`` の保守値を使う。"
                                "name は素直に: 'ジョグ', 'ランニング', 'ラッキング', 'VR boxing', '木刀素振り: 大素振り' 等。"
                                "心拍ターゲット・ペース等の詳細は notes に書く (心拍は絶対値・単一値、ゾーン記法 Z1/Z2 は禁止)"
                            ),
                            "items": {
                                "type": "object",
                                "required": ["name", "sets", "reps"],
                                "properties": {
                                    "name": {
                                        "type": "string",
                                        "description": "種目名。例: 'ダンベルベンチプレス'",
                                    },
                                    "weight": {
                                        "type": "string",
                                        "description": (
                                            "重量を文字列で。'12kg×2' (両手ダンベル) / '16kg' (片手ゴブレット) / '自重' / 'バッグ 8kg' 等。"
                                            "ヒンジ系 (RDL, デッドリフト) は腰を痛めた経験から **12kg 上限**。"
                                        ),
                                    },
                                    "sets": {
                                        "type": "integer",
                                        "description": "セット数 (通常 3-4)",
                                    },
                                    "reps": {
                                        "type": "string",
                                        "description": "回数。'10' or '8-12' or '60秒' (時間制)",
                                    },
                                    "rest_sec": {
                                        "type": "integer",
                                        "description": (
                                            "セット間休憩秒。Hypertrophy 60-90s / Strength 120-180s / Endurance 30-60s"
                                        ),
                                    },
                                    "rir": {
                                        "type": "integer",
                                        "description": (
                                            "Reps in Reserve (限界まで何 reps 余力残すか)。"
                                            "Hypertrophy 1-3、Strength 1-2、技術習得は 3-5"
                                        ),
                                    },
                                    "tempo": {
                                        "type": "string",
                                        "description": "テンポ表記。'2-1-2-0' (eccentric-pause-concentric-pause) 等、必要時のみ",
                                    },
                                    "notes": {
                                        "type": "string",
                                        "description": "フォーム注意・代替案など 1 文",
                                    },
                                },
                            },
                        },
                        "why": {
                            "type": "string",
                            "description": "選定理由を 1 文で簡潔に。科学的根拠 (volume, ACWR, 回復状態) を 1 つ引用",
                        },
                    },
                },
            },
            "rationale": {
                "type": "string",
                "maxLength": 320,
                "description": (
                    "**必須**。focus とは別に、判断根拠を 2-3 文で記述する (なぜこの強度・モダリティ・栄養指示を選んだか)。"
                    "最も寄与したスコアまたはメトリクスを引用する (例: 'BB 36 / ACWR 1.8 / 直近 3 日連続筋トレ' 等)。"
                    "focus と内容を重複させず、focus の決定理由をここに書く。"
                    "XML 風タグや疑似ツール記法は絶対に含めない。"
                ),
            },
        },
    },
}


def build_messages(
    *,
    target: date_type,
    today_payload: dict[str, Any],
    baselines: dict[str, Any],
    calendar_events: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (system_blocks, messages) suitable for the Anthropic SDK."""
    system_blocks = [
        {"type": "text", "text": _format_persona(), "cache_control": {"type": "ephemeral"}},
        {
            "type": "text",
            "text": build_baseline_block(baselines),
            "cache_control": {"type": "ephemeral"},
        },
    ]
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": build_user_block(
                        target, today_payload, calendar_events=calendar_events
                    ),
                }
            ],
        }
    ]
    return system_blocks, messages
