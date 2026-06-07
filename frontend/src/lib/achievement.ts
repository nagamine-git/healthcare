/**
 * 達成度 (0-100) → 状態の単一ソース。
 * StatusLamps / LifeSection など複数箇所で閾値がドリフトしないよう一元化する。
 * パレット (色の濃淡) は文脈ごとに最適なものを各コンポーネントで選ぶ。
 */
export type AchState = "good" | "warn" | "bad" | "off";

export const ACH_GOOD = 70;
export const ACH_WARN = 40;

export function achState(value: number | null | undefined): AchState {
  if (value == null) return "off";
  if (value >= ACH_GOOD) return "good";
  if (value >= ACH_WARN) return "warn";
  return "bad";
}
