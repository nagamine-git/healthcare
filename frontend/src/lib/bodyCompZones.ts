/**
 * 体組成マップに重ねる「目的別ゾーン」の定義 (科学的エビデンスつき)。
 *
 * 平面: X=体重(kg) / Y=体脂肪率(%)。各ゾーンは (体脂肪率 × FFMI) または BMI 帯で定義し、
 * 身長に応じて体重へ変換する。エビデンス強度を明記し、弱いものはそう表示する。
 *
 * 出典 (要約):
 * - 健康: WHO BMI 18.5–24.9 / 男性の許容体脂肪 ~8–20% (ACSM, ACE)。エビデンス強。
 * - 体力(疲れにくさ): 相対 VO2max は体脂肪率と逆相関、十分な筋量が work capacity を支える。
 *   高体脂肪は持久力低下・低筋量は易疲労 (ACSM)。中程度の低体脂肪+適度な筋量。エビデンス中。
 * - 実用的な強さ/ミリタリー: 筋量多め(FFMI~20–23)×体脂肪を一定以下に。米軍の体脂肪上限規格
 *   + 筋力競技の体組成。エビデンス中。
 * - 魅力: 男性の魅力知覚研究 (体脂肪~10–15%・適度な筋肉/肩幅比、Sell 2017, Brierley 2016)。
 *   主観評価ベースなのでエビデンス弱。
 */

export type Evidence = "strong" | "moderate" | "weak";

export type Zone = {
  key: string;
  label: string;
  evidence: Evidence;
  fill: string;
  stroke: string;
  source: string;
} & (
  | { kind: "ffmi"; bf: [number, number]; ffmi: [number, number] }
  | { kind: "bmi"; bf: [number, number]; bmi: [number, number] }
);

// 女性は必須脂肪が高いので体脂肪域を +6% シフトする
function shiftBf(bf: [number, number], sex: "male" | "female"): [number, number] {
  const d = sex === "female" ? 6 : 0;
  return [bf[0] + d, bf[1] + d];
}

export function zonesFor(sex: "male" | "female"): Zone[] {
  const s = (bf: [number, number]) => shiftBf(bf, sex);
  return [
    {
      key: "health", label: "健康", evidence: "strong",
      fill: "rgba(52,211,153,0.14)", stroke: "rgba(52,211,153,0.5)",
      source: "WHO BMI 18.5–24.9 + 体脂肪 ~8–20% (ACSM)",
      kind: "bmi", bf: s([6, 20]), bmi: [18.5, 24.9],
    },
    {
      key: "stamina", label: "体力 (疲れにくさ)", evidence: "moderate",
      fill: "rgba(56,189,248,0.13)", stroke: "rgba(56,189,248,0.5)",
      source: "相対VO2maxは体脂肪と逆相関・筋量がwork capacityを支える (ACSM)",
      kind: "ffmi", bf: s([9, 16]), ffmi: [18.5, 21.5],
    },
    {
      key: "tactical", label: "実用的な強さ (ミリタリー)", evidence: "moderate",
      fill: "rgba(168,162,158,0.16)", stroke: "rgba(214,211,209,0.55)",
      source: "筋力競技の体組成 + 米軍 体脂肪上限規格",
      kind: "ffmi", bf: s([10, 18]), ffmi: [20, 23],
    },
    {
      key: "attractive", label: "魅力 (エビデンス弱)", evidence: "weak",
      fill: "rgba(244,114,182,0.12)", stroke: "rgba(244,114,182,0.45)",
      source: "男性の魅力知覚研究 (主観評価, Sell 2017 ほか)",
      kind: "ffmi", bf: s([10, 15]), ffmi: [19, 21.5],
    },
  ];
}

/** (身長, 体脂肪率, 正規化FFMI) → 体重kg。バックエンド body_composition.py と一致。 */
export function weightAt(heightCm: number, bodyFat: number, ffmiNorm: number): number {
  const h = heightCm / 100;
  const ffmiRaw = ffmiNorm - 6.1 * (1.8 - h);
  const lbm = ffmiRaw * h * h;
  return lbm / (1 - bodyFat / 100);
}

export function weightForBmi(heightCm: number, bmi: number): number {
  const h = heightCm / 100;
  return bmi * h * h;
}

export const EVIDENCE_LABEL: Record<Evidence, string> = {
  strong: "エビデンス強",
  moderate: "エビデンス中",
  weak: "エビデンス弱",
};
