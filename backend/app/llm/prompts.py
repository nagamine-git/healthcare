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
- 週スプリットの参考: {weekly_split_hint}

# 出力ルール
- 全体で 450 字以内、絵文字なし、丁寧体、断定調を避けベースライン比で語る
- 推奨時刻は本日の現在時刻以降を JST で 24h 表記、所要時間は分単位
- 既存のカレンダー予定がある時間帯は **基本的に避ける** (会議等)。直前/直後 5 分のバッファも空けて提案する
- ただし、``is_adjustable=true`` の予定は Healthcare が再提案で **置き換え可能**。コンディション上不要なら省略 / 内容や時刻を最適化して別タイトルで提案して良い
- 専門用語 (例: ラッキング, Z2, RPE, ACWR) を使う場合は、初出に括弧で **短い補足を必ず付ける**。例: 「ラッキング (重い荷物を背負って歩く)」「Z2 (会話可能な低強度有酸素、心拍 110-130)」「RPE 6 (10 段階の主観強度、ややきつい)」
- ケガ歴を尊重: 腰に高負荷をかけるヒンジ系は安全重量に抑える
- 仕事のパフォーマンスを最優先。HRV/Body Battery が低い日は強度を落とす
- HIIT は週 1〜2 回、それ以上は推奨しない
- 体脂肪率は「目標範囲」の中で語り、過度な減量は推奨しない
- body_battery は「朝の値」と「現在値」が両方ある場合、現在値を基準に「いま何ができるか」で語る
- **必要なアクションだけを提案** (1 個でも良い)。穴埋めで増やさない
- **直近 7 日 (recent_workouts_7d)** を確認し、同じ種目を毎日連続で組まない。回復日を意識し、刺激のバリエーションを混ぜる
- 既にスケジュール済みの予定 (例: 21:00 筋トレ) を尊重し、その前後の準備/補助だけを提案するなら 1 件で十分

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

トレーニングの場合は **必ず候補種目から選び**、扱う重量を intensity に明示する。

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
        weekly_split_hint=s.user_weekly_split_hint,
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
        parts.append("# 既存のカレンダー予定 (この時間帯は推奨アクションを入れない)")
        for ev in calendar_events:
            start = ev.get("start", "")
            end = ev.get("end", "")
            summary = ev.get("summary", "")
            busy = "" if ev.get("is_busy", True) else " (空き扱い)"
            # ISO 文字列から HH:MM を抽出
            try:
                s_hm = datetime.fromisoformat(start).astimezone(ZoneInfo("Asia/Tokyo")).strftime("%H:%M")
                e_hm = datetime.fromisoformat(end).astimezone(ZoneInfo("Asia/Tokyo")).strftime("%H:%M")
                parts.append(f"- {s_hm}–{e_hm} {summary}{busy}")
            except Exception:
                parts.append(f"- {start}–{end} {summary}{busy}")
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
                "description": "1〜2 文で今日の状態と方針を述べる (詳細)。日本語。",
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
                            "description": "アクション名。短く。例: ラッキング Z2 / ダンベルスクワット 12kg×2 / 軽食",
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
                            "description": "RPE / 重量 / 距離 / ペースなどの強度指定。training/cardio で必須。",
                        },
                        "why": {
                            "type": "string",
                            "description": "選定理由を 1 文で簡潔に。",
                        },
                    },
                },
            },
            "rationale": {
                "type": "string",
                "description": "1 文で、最も寄与したスコアまたはメトリクスを 1 つ引用する。",
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
