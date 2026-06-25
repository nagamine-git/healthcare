import type { CSSProperties } from "react";

/**
 * 庭の草マスの色を 2 軸で決める。
 * - 色軸(白↔緑): focus(重点度 0..1)。重点(盲点)に効く努力ほど緑、
 *   すでに強い領域への努力ほど白っぽく(低彩度・高明度)。
 * - 濃淡軸(透明度): level(0..4)。量が多いほど濃く(不透明)。
 * level<=0(活動なし)は null を返し、呼び出し側で空マス色を当てる。
 */
export function gardenCellStyle(level: number, focus: number): CSSProperties | null {
  if (level <= 0) return null;
  const f = Math.max(0, Math.min(1, focus));
  const sat = Math.round(10 + f * 65); // 白(低彩度)→ 緑(高彩度)
  const light = Math.round(88 - f * 42); // 白(高明度)→ 緑(中明度)
  const opacity = 0.3 + (Math.min(level, 4) / 4) * 0.7; // 量で濃淡
  return { backgroundColor: `hsl(152, ${sat}%, ${light}%)`, opacity };
}
