"""周径測定 (ウエスト/首/胸/ヒップ) から体型を評価する DB 非依存の純粋関数群。

# なぜ周径を測るか
体組成計 (BIA) の体脂肪率は誤差 ±3-5% あり、体水分量 (食事・塩分・発汗・ホルモン周期)
に強く影響されて日内変動する (Kyle et al. 2004 Clin Nutr; Dehghan & Merchant 2008
Nutr J)。体重・体脂肪率だけでは体型評価の裏付けとして弱い。

周径 (メジャーでの直接測定) は測定誤差が小さく体水分にも左右されないため、
BIA とは独立した2本目の評価軸になる。両者が一致すれば信頼度が上がり、乖離すれば
BIA 側が(体水分変動などで)荒れていると判断できる。

## WHtR (Waist-to-Height Ratio, ウエスト身長比)
ウエスト周径 ÷ 身長。「ウエストは身長の半分未満に (keep your waist to less than
half your height)」という単純な公衆衛生メッセージとして国際的に検証されており、
英国 NICE は 2022 年更新のガイダンス (NG246, 旧 CG189 を統合) で成人の中心性肥満
スクリーニングに WHtR を採用した。男性は内臓脂肪が腹部に優先的に蓄積するため、
WHtR の心血管代謝リスク予測力は BMI や体脂肪率より高いとされる
(Ashwell & Gibson 2016, meta-analysis; Browning et al. 2010, systematic review)。

## 米海軍式体脂肪率 (Hodgdon & Beckett 1984)
Naval Health Research Center Report No. 84-11 で発表された周径ベースの体脂肪率
推定式。体水分の影響を受けないため BIA の体脂肪率と独立した2本目の推定値になる。
原著の DEXA/水中体重法との標準誤差 (SEE) は男性で約 3.5%。

男性: %BF = 86.010 * log10(waist - neck) - 70.041 * log10(height) + 36.76

女性版は hip 周径が追加で必要な別式であり、本アプリは単一ユーザー(男性)前提なので
実装しない。sex が female の場合は誤った値を出さないよう None を返す。

**単位に関する注意 (重要)**: 上式の係数 (86.010 / 70.041 / 36.76) は原著論文で
インチ単位の測定値に対して較正されている。cm の値をそのまま代入すると単位不整合
により体脂肪率が systematically 過大評価される。
実例で検証済み: waist=85cm, neck=38cm, height=170cm のとき
  - cm をそのまま代入 (誤り): 約 24.4%
  - cm→インチへ変換してから代入 (正しい): 約 17.9%
このアプリの入力は他の身体測定と統一して cm で保持するため、本モジュールは
内部でインチへ変換してから原式を適用する (数式としては原著と同一、単位だけ変換)。
"""

from __future__ import annotations

import math

# --- WHtR の判定閾値 (clinical: NICE NG246 2022, Ashwell & Gibson 2016) ---
# 0.5 未満: 良好の目安 ("ウエストは身長の半分未満")。
# 0.5-0.6: 要注意 (中心性肥満のリスクが増え始める帯)。
# 0.6 以上: 高リスク。
WHTR_GOOD_MAX = 0.5
WHTR_CAUTION_MAX = 0.6

# --- 米海軍式体脂肪率の係数 (Hodgdon & Beckett 1984, インチ較正) ---
_NAVY_WAIST_NECK_COEF = 86.010
_NAVY_HEIGHT_COEF = 70.041
_NAVY_CONST = 36.76
_CM_PER_IN = 2.54

# BIA とのぶれを「大きな乖離」と見なす閾値 (pt)。BIA の測定誤差 ±3-5% を踏まえ、
# それより一回り広めに取って偽陽性 (単なる測定誤差での警告) を減らす。
NAVY_BIA_DISCREPANCY_PT = 6.0


def whtr(waist_cm: float | None, height_cm: float | None) -> float | None:
    """WHtR (ウエスト身長比) を返す。欠測・不正値は None。"""
    if waist_cm is None or height_cm is None or height_cm <= 0 or waist_cm <= 0:
        return None
    return round(waist_cm / height_cm, 3)


def whtr_status(ratio: float | None) -> str | None:
    """WHtR の判定。"good" (0.5未満) / "caution" (0.5-0.6) / "high" (0.6以上)。"""
    if ratio is None:
        return None
    if ratio < WHTR_GOOD_MAX:
        return "good"
    if ratio < WHTR_CAUTION_MAX:
        return "caution"
    return "high"


def navy_body_fat_pct(
    waist_cm: float | None,
    neck_cm: float | None,
    height_cm: float | None,
    sex: str | None,
) -> float | None:
    """米海軍式(周径法)体脂肪率の推定 (男性のみ)。

    女性は hip 周径が必要な別式であり未実装のため、sex が female (or 不明) なら
    誤った値を返さず None にする。waist <= neck (測定ミス/異常値) や欠測も None。
    """
    if sex is None or not sex.strip().lower().startswith("m"):
        return None
    if waist_cm is None or neck_cm is None or height_cm is None:
        return None
    if height_cm <= 0 or waist_cm <= 0 or neck_cm <= 0:
        return None
    diff_cm = waist_cm - neck_cm
    if diff_cm <= 0:  # 首がウエストより太いのは測定ミス/異常値
        return None

    # 原式はインチ較正なので cm→インチへ変換してから代入する (docstring 参照)。
    diff_in = diff_cm / _CM_PER_IN
    height_in = height_cm / _CM_PER_IN

    pct = (
        _NAVY_WAIST_NECK_COEF * math.log10(diff_in)
        - _NAVY_HEIGHT_COEF * math.log10(height_in)
        + _NAVY_CONST
    )
    return round(pct, 1)


def bia_navy_discrepancy(bia_body_fat_pct: float | None, navy_pct: float | None) -> dict | None:
    """BIA 体脂肪率と米海軍式推定の乖離をまとめる (2本立て表示用)。

    どちらか欠測なら None。乖離が NAVY_BIA_DISCREPANCY_PT 以上なら
    "large"(片方の測定・体水分状態が荒れている可能性)、それ未満は "close"(一致)。
    """
    if bia_body_fat_pct is None or navy_pct is None:
        return None
    diff = round(bia_body_fat_pct - navy_pct, 1)
    return {
        "bia_pct": bia_body_fat_pct,
        "navy_pct": navy_pct,
        "diff_pt": diff,
        "status": "large" if abs(diff) >= NAVY_BIA_DISCREPANCY_PT else "close",
    }
