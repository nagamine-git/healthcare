/**
 * パラメトリックな体型シルエット (SVG)。
 * - bodyFat (10-22%) で胴・腹の幅が変わる (体脂肪が高いほど太い)
 * - ffmi (18-22) で肩・腕の幅が変わる (筋肉が多いほど広い)
 * - sex で骨格 (肩幅/腰幅の比) を変える
 * 写真ではなく抽象シルエットなので、体組成の "見た目の違い" だけを誠実に示す。
 */
import { P } from "../lib/palette";
export function Silhouette({
  bodyFat,
  ffmi,
  sex,
  size = 56,
  active = false,
}: {
  bodyFat: number;
  ffmi: number;
  sex: "male" | "female";
  size?: number;
  active?: boolean;
}) {
  // 正規化: 体脂肪 10-22 → 0..1、FFMI 18-22 → 0..1
  const fat = Math.max(0, Math.min(1, (bodyFat - 10) / 12));
  const muscle = Math.max(0, Math.min(1, (ffmi - 18) / 4));

  // 肩幅: 筋肉で広がる。男性はベース広め
  const shoulder = (sex === "male" ? 15 : 12) + muscle * 7;
  // ウエスト: 体脂肪で太る。女性は腰がやや広い基準
  const waist = (sex === "male" ? 8 : 9) + fat * 7;
  // 胸/腹の張り
  const chest = (sex === "male" ? 11 : 10) + muscle * 3 + fat * 2;
  const hip = (sex === "male" ? 9 : 11) + fat * 4;

  const cx = 32;
  const color = active ? P.prog300 : P.inkFaint;

  // 体の輪郭 (頭→肩→ウエスト→腰→脚) を左右対称のパスで
  const body = [
    `M ${cx - chest} 22`,
    `C ${cx - shoulder} 20, ${cx - shoulder} 26, ${cx - shoulder} 30`,
    `C ${cx - shoulder} 36, ${cx - waist} 40, ${cx - waist} 46`,
    `C ${cx - waist} 52, ${cx - hip} 54, ${cx - hip} 62`,
    `L ${cx - hip * 0.5} 92`,
    `L ${cx - 2} 92`,
    `L ${cx - 2} 60`,
    `L ${cx + 2} 60`,
    `L ${cx + 2} 92`,
    `L ${cx + hip * 0.5} 92`,
    `L ${cx + hip} 62`,
    `C ${cx + hip} 54, ${cx + waist} 52, ${cx + waist} 46`,
    `C ${cx + waist} 40, ${cx + shoulder} 36, ${cx + shoulder} 30`,
    `C ${cx + shoulder} 26, ${cx + shoulder} 20, ${cx + chest} 22`,
    "Z",
  ].join(" ");

  return (
    <svg viewBox="0 0 64 96" width={size} height={size * 1.5} aria-hidden>
      {/* 頭 */}
      <circle cx={cx} cy={11} r={7} fill={color} />
      {/* 胴体 */}
      <path d={body} fill={color} />
    </svg>
  );
}
