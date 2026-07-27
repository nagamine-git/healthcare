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

# 各パターンの主種目 (固定・漸進)。各日の第1種目が実質の主軸。
# ダンベル日と自重日を強度日ごとに交互ローテ (mode) して両方を定期的に回す。
#
# ⚠️ **上半身は BIG3 を主軸に、下半身は片脚種目を主軸にする**。理由は機材の上限:
# 固定ダンベルは 2/4/8/12/16/20kg しか無く、両脚種目は「脚が疲れる前に別の要因で終わる」。
#   - ベンチ:     20kg×2 = 40kg → 胸の刺激として十分。主軸として機能する
#   - 両脚スクワット: 20kg×2 = 40kg → 脚には軽く、先に**握力と上背部**が限界になる
#   - 両脚RDL:    腰の既往 (user_injury_notes: 16kgで受傷、ヒンジ系は12kg以下) で
#                 12kg×2 = 24kg が上限。ヒンジの強度ドライバーにはなり得ない
# 筋肥大を決めるのは週あたりの追い込んだセット数と漸進性であって種目そのものではない
# (Schoenfeld らのボリューム研究)。荷重を増やせない環境では **片脚化で実効負荷を倍にする**のが
# 最も素直な漸進手段になる。片脚RDL は両脚で高重量を持つより脊柱への剪断力が小さく、
# ハムに集中できるので既往への安全性でも優る。
# ゴブレットは**プレート (1kg刻み・計36kg)** を使えばダンベルより細かく重くできるので、
# 下半身で漸進性を作れる数少ない両脚種目として補助に残す。
MAIN_LIFTS_DB = {
    "push": ["ダンベルベンチプレス", "ダンベルショルダープレス"],
    # pull の主軸は片手ロー (20kg まで使える)。RDL は 12kg 上限で強度を出せないため、
    # ハムのストレッチと動作パターン維持の種目として第2に置く。
    "pull": ["ダンベルロー (片手)", "ダンベルRDL (ルーマニアンデッドリフト・12kg上限/腰既往)"],
    # legs の主軸は片脚。同じダンベルで実効負荷が倍になり、漸進の余地が残る。
    "legs": ["ブルガリアンスクワット (ベンチ・片脚)", "ダンベルゴブレットスクワット (プレートで漸進)"],
}
# 自重 BIG3。懸垂バー/マシンは無い前提 → pull は机/ドア/タオルで代替する no-bar 種目。
# 自重 BIG3。ただし懸垂バー/机-ロー環境が無いため、引く動作だけは器具ゼロで代替できないので
# ダンベルロー + 自重の背面種目で構成する (pull は自重化しきれない現実に合わせる)。
MAIN_LIFTS_BW = {
    "push": ["腕立て伏せ (デクライン(足をベンチ)/ダイヤモンド/ワイド)", "パイクプッシュアップ"],
    "pull": ["ダンベルロー (片手・懸垂環境が無いため引く動作はダンベル)", "スーパーマン (背面伸展・自重)"],
    "legs": ["自重スクワット (スロー/ジャンプ)", "ブルガリアンスクワット (ベンチ) or ピストル"],
}
MODE_LABEL = {"dumbbell": "ダンベル BIG3", "bodyweight": "自重 BIG3"}

# 補助種目 (日替わりローテで単調さ回避)。
ACCESSORIES = {
    "push": ["ダンベルフライ", "サイドレイズ", "ダンベルフレンチプレス", "腕立て伏せ (デクライン)"],
    "pull": ["ダンベルカール", "ハンマーカール", "ダンベルリアレイズ", "ダンベルシュラッグ"],
    # ブルガリアンは主種目に格上げしたのでここからは外す (同日に重複させない)。
    # 片脚RDL を補助に入れ、ヒンジを「重量ではなく片脚化」で刺激する。
    "legs": ["カーフレイズ (ダンベル加重)", "ダンベルランジ", "ダンベルステップアップ",
             "片脚ルーマニアンデッドリフト (バランス+ハム)", "ヒップスラスト"],
}

# 体幹 (各筋トレ日にローテで 1 つ)。アブローラーは無いのでマット/ダンベルで可能な種目のみ。
CORE = ["プランク (前腕/サイド)", "レッグレイズ", "ダンベルサイドベンド", "デッドバグ"]

# 有酸素モダリティのローテ順 (嗜好: 素振り・HIIT を前に、ランニング/シャドーは控えめ)。
CARDIO_ROTATION = ["kata", "hiit", "z2"]
CARDIO_DETAIL = {
    "hiit": "HIIT: タバタ形式 (20秒全力+10秒休×8) を王道の単純種目で — ダンベルプッシュプレス/"
            "ダンベルクリーン/静音バーピー(ジャンプ無し)/自重スクワット/マウンテンクライマー のいずれか "
            "(心拍 150、時間効率重視。ジャンプは階下騒音のため不可)",
    "kata": "木刀素振り連続 (蹲踞/股割り、心拍 135、Z2 + 技術)",
    "z2": "Z2 有酸素: ジョグ (屋外) or 室内その場足踏み・軽シャドー (心拍 125)",
}
CARDIO_LABEL = {"hiit": "HIIT", "kata": "素振り (剣道)", "z2": "Z2 有酸素"}


def strength_split(*, strength_total: int, day_ordinal: int) -> dict[str, Any]:
    """今日の筋トレ内容 (押/引/脚のどれか + 主種目 + 補助 + 体幹)。

    - strength_total: 過去の筋トレ回数 (これで押→引→脚を順に回す)
    - day_ordinal: 日付序数 (補助/体幹のローテ用・乱数不使用で決定論)
    """
    pattern = PATTERNS[strength_total % len(PATTERNS)]
    # ダンベル ⇄ 自重 を強度セッションごとに交互 (各パターンが DB/自重 を定期的に回る)
    mode = "bodyweight" if strength_total % 2 else "dumbbell"
    mains = MAIN_LIFTS_BW if mode == "bodyweight" else MAIN_LIFTS_DB
    accs = ACCESSORIES[pattern]
    return {
        "pattern": pattern,
        "label": PATTERN_LABEL[pattern],
        "mode": mode,
        "mode_label": MODE_LABEL[mode],
        "main_lifts": list(mains[pattern]),
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
