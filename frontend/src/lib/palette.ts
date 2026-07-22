/**
 * デザイントークンの TS 値版。SVG 属性・Recharts・inline style など
 * Tailwind クラスを書けない場所はここを import する。
 *
 * ライト/ダーク対応: 値は index.css の CSS 変数 (--c-*) から実行時に解決する。
 * `P.void` の呼び出し方は据え置きで、テーマ切替時に `refreshPalette()` が
 * キャッシュを更新する (useTheme が呼ぶ)。DOM が無い/未解決の初回は下の
 * FALLBACK (ダーク値) を返すので安全。
 */

// トークン名 → CSS 変数名。
const VARS: Record<string, string> = {
  void: "--c-void",
  hull: "--c-hull",
  panel: "--c-panel",
  hairline: "--c-hairline",
  ink: "--c-ink",
  inkDim: "--c-ink-dim",
  inkFaint: "--c-ink-faint",
  prog: "--c-prog",
  prog300: "--c-prog-300",
  act: "--c-act",
  act300: "--c-act-300",
  risk: "--c-risk",
  risk300: "--c-risk-300",
  info: "--c-info",
  info300: "--c-info-300",
};

// CSS 変数を読めない時のフォールバック (= ダークの実値)。
// 700 系はテーマ非依存 (どちらの地でも暗色で成立) なのでここに literal で持つ。
const FALLBACK: Record<string, string> = {
  void: "#06080c",
  hull: "#0f141d",
  panel: "#1a212e",
  hairline: "#222c3b",
  ink: "#eef2f8",
  inkDim: "#9fabbd",
  inkFaint: "#69748a",
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
};

const cache: Record<string, string> = { ...FALLBACK };

/** CSS 変数の現在値を読み直してキャッシュを更新する。テーマ切替時に呼ぶ。 */
export function refreshPalette(): void {
  if (typeof document === "undefined") return;
  const cs = getComputedStyle(document.documentElement);
  for (const [key, cssVar] of Object.entries(VARS)) {
    const channels = cs.getPropertyValue(cssVar).trim(); // 例 "6 8 12"
    if (channels) cache[key] = `rgb(${channels.split(/\s+/).join(", ")})`;
  }
}

// 初回評価時に一度解決 (data-theme は index.html のインラインスクリプトで確定済み)。
refreshPalette();

export type PaletteKey = keyof typeof VARS | "prog700" | "act700" | "info500";

/** テーマ追従の値マップ。`P.void` の形はそのまま使える。 */
export const P: Record<PaletteKey, string> = new Proxy({} as Record<PaletteKey, string>, {
  get: (_t, key: string) => cache[key] ?? FALLBACK[key] ?? "#000",
});
