"""週次トレーニング・フレームワーク (決定論)。

「毎回同じ3種目」「有酸素/HIIT/素振りが出ない」への対策。週を意図的に配分し、今日の
モダリティと (筋トレなら) 押す/引く/脚スプリット + 主種目/補助を決めて LLM に渡す。

方針 (体組成重視 × タイパ × 嗜好):
- 筋トレ (ダンベル BIG, 押/引/脚ローテ) を週 3 = 体組成の核・漸進性過負荷。主種目は固定・漸進。
- 有酸素系を週 3 = HIIT / 素振り(剣道) / Z2 をローテ。嗜好により素振り・HIIT を優先し
  ランニング/シャドーは控えめ。補助種目は日替わりで単調さを回避。
- 週目標に対する「不足」が大きい側を今日選ぶ (回復/ACWR の最終調整は下流に委ねる)。

科学的根拠: 進捗は主要種目の一貫した漸進で最大化する (種目を毎回変えると漸進性が崩れる)。
一方で補助種目・有酸素モダリティのローテは飽き防止と全身の網羅に有効。HIIT は時間効率の高い
体脂肪/心肺刺激、Z2 は回復と有酸素基盤。剣道素振りは技術 + 中強度有酸素として両立する。
"""

from __future__ import annotations

from typing import Any

# 週の目標回数 (目安)。筋トレ 3・有酸素系 3。
STRENGTH_PER_WEEK = 3
CARDIO_PER_WEEK = 3

PATTERNS = ["push", "pull", "legs"]
PATTERN_LABEL = {"push": "押す (胸・肩・三頭)", "pull": "引く (背中・二頭)", "legs": "脚・臀"}

# 各パターンの主種目 (固定・漸進)。ダンベル BIG 中心。
MAIN_LIFTS = {
    "push": ["ダンベルベンチプレス", "ダンベルショルダープレス"],
    "pull": ["ダンベルロー (片手)", "ダンベルRDL (ルーマニアンデッドリフト)"],
    "legs": ["ダンベルゴブレットスクワット", "ダンベルランジ"],
}

# 補助種目 (日替わりローテで単調さ回避)。
ACCESSORIES = {
    "push": ["ダンベルフライ", "サイドレイズ", "ダンベルフレンチプレス", "腕立て伏せ (デクライン)"],
    "pull": ["ダンベルカール", "ハンマーカール", "ダンベルリアレイズ", "ダンベルシュラッグ"],
    "legs": ["カーフレイズ (ダンベル加重)", "ブルガリアンスクワット", "ダンベルステップアップ",
             "ヒップスラスト"],
}

# 体幹 (各筋トレ日にローテで 1 つ)。
CORE = ["アブローラー (膝つき)", "プランク", "レッグレイズ", "ダンベルサイドベンド"]

# 有酸素モダリティのローテ順 (嗜好: 素振り・HIIT を前に、ランニング/シャドーは控えめ)。
CARDIO_ROTATION = ["kata", "hiit", "z2"]
CARDIO_DETAIL = {
    "hiit": "HIIT: タバタ or ダンベルコンプレックス (心拍 150、時間効率重視)",
    "kata": "木刀素振り連続 (蹲踞/股割り、心拍 135、Z2 + 技術)",
    "z2": "Z2 有酸素: ラッキング (リュック 5kg、心拍 125) or ジョグ",
}
CARDIO_LABEL = {"hiit": "HIIT", "kata": "素振り (剣道)", "z2": "Z2 有酸素"}


def strength_split(*, strength_total: int, day_ordinal: int) -> dict[str, Any]:
    """今日の筋トレ内容 (押/引/脚のどれか + 主種目 + 補助 + 体幹)。

    - strength_total: 過去の筋トレ回数 (これで押→引→脚を順に回す)
    - day_ordinal: 日付序数 (補助/体幹のローテ用・乱数不使用で決定論)
    """
    pattern = PATTERNS[strength_total % len(PATTERNS)]
    accs = ACCESSORIES[pattern]
    return {
        "pattern": pattern,
        "label": PATTERN_LABEL[pattern],
        "main_lifts": list(MAIN_LIFTS[pattern]),
        "accessory": accs[day_ordinal % len(accs)],
        "core": CORE[day_ordinal % len(CORE)],
    }


def compute_today_training(
    *, strength_7d: int, cardio_7d: int, strength_total: int, day_ordinal: int
) -> dict[str, Any]:
    """今日のモダリティを週の不足から決める。筋トレなら split を、有酸素なら種別を返す。

    週目標に対する不足 (target − done) が大きい側を選ぶ。同点は体組成の核=筋トレ優先。
    """
    strength_deficit = STRENGTH_PER_WEEK - strength_7d
    cardio_deficit = CARDIO_PER_WEEK - cardio_7d
    if strength_deficit >= cardio_deficit:
        return {
            "modality": "strength",
            "split": strength_split(strength_total=strength_total, day_ordinal=day_ordinal),
            "weekly": {"strength_7d": strength_7d, "cardio_7d": cardio_7d,
                       "strength_target": STRENGTH_PER_WEEK, "cardio_target": CARDIO_PER_WEEK},
        }
    kind = CARDIO_ROTATION[cardio_7d % len(CARDIO_ROTATION)]
    return {
        "modality": kind,
        "label": CARDIO_LABEL[kind],
        "detail": CARDIO_DETAIL[kind],
        "weekly": {"strength_7d": strength_7d, "cardio_7d": cardio_7d,
                   "strength_target": STRENGTH_PER_WEEK, "cardio_target": CARDIO_PER_WEEK},
    }
