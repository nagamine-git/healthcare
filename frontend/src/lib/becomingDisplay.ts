import type { BecomingLoop } from "./api";

/** フライホイール診断の表示(ラベル + 色トーン)。Becoming/CockpitHero 共通。 */
export const DIAGNOSIS: Record<
  BecomingLoop["diagnosis"],
  { short: string; long: string; tone: "prog" | "act" | "neutral" }
> = {
  flywheel_turning: {
    short: "回っている",
    long: "フライホイールが回っています(動けた日に攻め、努力が盲点に向き、実際に前進)",
    tone: "prog",
  },
  wasted_capacity: {
    short: "資本の浪費",
    long: "資本の浪費:コンディションが良い日に攻められていません",
    tone: "act",
  },
  spinning: {
    short: "空回り",
    long: "空回り:努力はしているが前進していません(行動の選択を見直す)",
    tone: "act",
  },
  building: { short: "構築中", long: "構築中:データを貯めています", tone: "neutral" },
};

/** 到達日数を人間向けラベルへ。 */
export function etaLabel(days: number | null): string {
  if (days === null) return "—";
  if (days >= 60) return `${Math.round(days / 30)}ヶ月`;
  return `${days}日`;
}

/** 0..1 を百分率の整数文字列へ(null は —)。 */
export function pct(v: number | null): string {
  return v === null ? "—" : `${Math.round(v * 100)}`;
}
