/**
 * 人体シルエット (SVG)。部位ごとに色を塗って負荷/ステータスを示す。
 * 解剖プロポーションに寄せた抽象シルエット — 筋群の「どこが」を直感的に示す。
 * 背面表示 (fills.upperBack あり) のときは胸/腹を出さず背中を出す。
 */

export type ShapeKey =
  | "head" | "shoulderL" | "shoulderR" | "chest" | "abs"
  | "armL" | "armR" | "legL" | "legR" | "upperBack";

const FAINT = "#334155";
const STRUCT = "#1e293b"; // 首・手・足など構造パーツ

// viewBox 0 0 100 150 上の各部位パス (解剖プロポーションに補正)
const D: Record<ShapeKey, string> = {
  head: "M50 6 C57 6 59 12 58 18 C57 23 54 26 50 26 C46 26 43 23 42 18 C41 12 43 6 50 6 Z",
  shoulderL: "M40 33 C33 31 26 34 25 42 C25 47 29 49 34 47 C38 46 41 42 40 33 Z",
  shoulderR: "M60 33 C67 31 74 34 75 42 C75 47 71 49 66 47 C62 46 59 42 60 33 Z",
  chest: "M40 33 C46 31 54 31 60 33 C62 40 61 48 56 53 C53 55 47 55 44 53 C39 48 38 40 40 33 Z",
  abs: "M44 52 C47 54 53 54 56 52 C57 60 57 70 55 78 C54 82 52 84 50 84 C48 84 46 82 45 78 C43 70 43 60 44 52 Z",
  armL: "M34 46 C29 46 26 50 25 57 C23 70 22 84 23 95 C23 99 27 100 29 97 C30 84 31 70 33 56 C34 51 34 48 34 46 Z",
  armR: "M66 46 C71 46 74 50 75 57 C77 70 78 84 77 95 C77 99 73 100 71 97 C70 84 69 70 67 56 C66 51 66 48 66 46 Z",
  legL: "M48 80 C49 82 49 84 49 88 C49 102 48 116 46 128 C45 137 44 145 43 148 C42 150 39 150 38 147 C37 138 37 126 38 114 C39 102 41 90 44 81 C45 80 47 80 48 80 Z",
  legR: "M52 80 C51 82 51 84 51 88 C51 102 52 116 54 128 C55 137 56 145 57 148 C58 150 61 150 62 147 C63 138 63 126 62 114 C61 102 59 90 56 81 C55 80 53 80 52 80 Z",
  upperBack: "M40 33 C46 31 54 31 60 33 C62 42 62 54 58 62 C53 65 47 65 42 62 C38 54 38 42 40 33 Z",
};

export function BodyFigure({
  fills,
  suggested,
  size = 92,
}: {
  fills: Partial<Record<ShapeKey, string>>;
  suggested?: Partial<Record<ShapeKey, boolean>>;
  size?: number;
}) {
  const isBack = fills.upperBack != null;
  const region = (k: ShapeKey) => (
    <path
      key={k}
      d={D[k]}
      fill={fills[k] ?? FAINT}
      stroke={suggested?.[k] ? "#fbbf24" : "#0f172a"}
      strokeWidth={suggested?.[k] ? 1.8 : 0.5}
    />
  );
  return (
    <svg viewBox="0 0 100 150" width={size} height={(size * 150) / 100} role="img" aria-label="人体ステータス図">
      {/* 構造パーツ (首・手・足) は常に淡色 */}
      <path d="M46 24 H54 V31 H46 Z" fill={STRUCT} />
      <circle cx={27} cy={99} r={3} fill={STRUCT} />
      <circle cx={73} cy={99} r={3} fill={STRUCT} />
      <ellipse cx={39} cy={149} rx={4} ry={2} fill={STRUCT} />
      <ellipse cx={61} cy={149} rx={4} ry={2} fill={STRUCT} />
      {/* 部位 */}
      {region("head")}
      {region("shoulderL")}
      {region("shoulderR")}
      {region("armL")}
      {region("armR")}
      {isBack ? region("upperBack") : (<>{region("chest")}{region("abs")}</>)}
      {region("legL")}
      {region("legR")}
    </svg>
  );
}
