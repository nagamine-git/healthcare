/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          "SF Pro Text",
          "ui-sans-serif",
          "Hiragino Sans",
          "Yu Gothic UI",
          "Noto Sans JP",
          "sans-serif",
        ],
        // 見出し・数値: Space Grotesk(tabular)。未読込時はシステムへ。
        display: ['"Space Grotesk"', "ui-sans-serif", "system-ui", "sans-serif"],
      },
      colors: {
        // プレミアム iOS ダーク。void<hull<panel の順で面が持ち上がる(elevation)。
        void: "#06080c",
        hull: "#0f141d",
        panel: "#1a212e",
        hairline: "#222c3b",
        ink: "#eef2f8",
        "ink-dim": "#9fabbd",
        "ink-faint": "#69748a",
        prog: {
          DEFAULT: "#10b981",
          300: "#6ee7b7",
          500: "#10b981",
          700: "#047857",
          900: "#064e3b",
        },
        act: { DEFAULT: "#f59e0b", 300: "#fcd34d", 700: "#b45309" },
        risk: { DEFAULT: "#fb5b73", 300: "#fda4af", 700: "#be123c" },
        info: { DEFAULT: "#38bdf8", 300: "#7dd3fc", 500: "#0ea5e9", 700: "#0369a1" },
      },
      borderRadius: {
        card: "1.25rem", // iOS カードの大きめ角丸
        control: "0.875rem",
      },
      boxShadow: {
        // iOS 風の柔らかい層状シャドウ
        card: "0 1px 0 0 rgba(255,255,255,0.04) inset, 0 12px 32px -16px rgba(0,0,0,0.7)",
        float: "0 8px 28px -8px rgba(0,0,0,0.55)",
        instrument: "0 0 0 1px #222c3b, 0 8px 24px -12px rgba(0,0,0,0.6)",
        "glow-prog": "0 0 24px -6px rgba(16,185,129,0.4)",
        "glow-act": "0 0 24px -6px rgba(245,158,11,0.45)",
      },
    },
  },
  plugins: [],
};
