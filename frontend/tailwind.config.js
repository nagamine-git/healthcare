/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          "ui-sans-serif",
          "-apple-system",
          "BlinkMacSystemFont",
          "Hiragino Sans",
          "Yu Gothic UI",
          "Noto Sans JP",
          "sans-serif",
        ],
        // 計器盤の見出し・数値: Space Grotesk(tabular)。未読込時はシステムへ。
        display: ['"Space Grotesk"', "ui-sans-serif", "system-ui", "sans-serif"],
      },
      colors: {
        // cockpit パレット(ダークベース + セマンティック2色)
        void: "#0a0e14",
        hull: "#121821",
        panel: "#1a2230",
        hairline: "#243044",
        ink: "#e6edf3",
        "ink-dim": "#9aa7b8",
        "ink-faint": "#5b6675",
        prog: {
          DEFAULT: "#10b981",
          300: "#6ee7b7",
          500: "#10b981",
          700: "#047857",
          900: "#064e3b",
        },
        act: { DEFAULT: "#f59e0b", 300: "#fcd34d", 700: "#b45309" },
        risk: "#f43f5e",
        // info: 計測・副次アクション・データ系の中立アクセント(良/悪/行動のどれでもない)
        info: { DEFAULT: "#38bdf8", 300: "#7dd3fc", 500: "#0ea5e9", 700: "#0369a1" },
      },
      boxShadow: {
        // 計器の微発光
        instrument: "0 0 0 1px #243044, 0 8px 24px -12px rgba(0,0,0,0.6)",
        "glow-prog": "0 0 16px -4px rgba(16,185,129,0.35)",
        "glow-act": "0 0 16px -4px rgba(245,158,11,0.4)",
      },
    },
  },
  plugins: [],
};
