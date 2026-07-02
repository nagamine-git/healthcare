/**
 * デザイントークンの TS 定数版。SVG 属性・Recharts・inline style など
 * Tailwind クラスを書けない場所はここを import する (tailwind.config.js と同値)。
 * 生 hex をコンポーネントに直書きしない — テーマの一貫性はこの1ファイルで担保する。
 */
export const P = {
  // elevation (void < hull < panel の順で面が持ち上がる)
  void: "#06080c",
  hull: "#0f141d",
  panel: "#1a212e",
  hairline: "#222c3b",
  // ink (テキスト)
  ink: "#eef2f8",
  inkDim: "#9fabbd",
  inkFaint: "#69748a",
  // semantic
  prog: "#10b981",
  prog300: "#6ee7b7",
  prog700: "#047857",
  act: "#f59e0b",
  act300: "#fcd34d",
  act700: "#b45309",
  risk: "#fb5b73",
  risk300: "#fda4af",
  info: "#38bdf8",
  info300: "#7dd3fc",
  info500: "#0ea5e9",
} as const;

export type PaletteKey = keyof typeof P;
