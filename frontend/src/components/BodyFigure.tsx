/**
 * 簡素な人体シルエット (SVG)。部位ごとに色を塗って負荷/ステータスを示す。
 * 解剖図ではなく抽象シルエット — 「どこが」を直感的に示すだけ。
 */

export type ShapeKey =
  | "head" | "shoulderL" | "shoulderR" | "chest" | "abs"
  | "armL" | "armR" | "legL" | "legR" | "upperBack";

const FAINT = "#334155";

export function BodyFigure({
  fills,
  suggested,
  size = 92,
}: {
  fills: Partial<Record<ShapeKey, string>>;
  suggested?: Partial<Record<ShapeKey, boolean>>;
  size?: number;
}) {
  const f = (k: ShapeKey) => fills[k] ?? FAINT;
  const ring = (k: ShapeKey) =>
    suggested?.[k] ? { stroke: "#fbbf24", strokeWidth: 2 } : {};
  return (
    <svg viewBox="0 0 100 150" width={size} height={(size * 150) / 100} role="img" aria-label="人体ステータス図">
      <circle cx={50} cy={14} r={9} fill={f("head")} {...ring("head")} />
      <ellipse cx={33} cy={35} rx={9} ry={7} fill={f("shoulderL")} {...ring("shoulderL")} />
      <ellipse cx={67} cy={35} rx={9} ry={7} fill={f("shoulderR")} {...ring("shoulderR")} />
      {/* 上胴 (胸/押す or 胸郭 or 背中) */}
      <rect x={37} y={31} width={26} height={31} rx={6} fill={f("chest")} {...ring("chest")} />
      {fills.upperBack && (
        <rect x={38} y={33} width={24} height={28} rx={6} fill={f("upperBack")} {...ring("upperBack")} />
      )}
      {/* 下胴 (体幹/腹) */}
      <rect x={39} y={63} width={22} height={25} rx={5} fill={f("abs")} {...ring("abs")} />
      {/* 腕 */}
      <rect x={21} y={33} width={9} height={43} rx={4} fill={f("armL")} {...ring("armL")} />
      <rect x={70} y={33} width={9} height={43} rx={4} fill={f("armR")} {...ring("armR")} />
      {/* 脚 */}
      <rect x={40} y={90} width={9} height={52} rx={4} fill={f("legL")} {...ring("legL")} />
      <rect x={51} y={90} width={9} height={52} rx={4} fill={f("legR")} {...ring("legR")} />
    </svg>
  );
}
