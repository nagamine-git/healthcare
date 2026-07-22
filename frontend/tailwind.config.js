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
        // 色は CSS 変数 (index.css の :root) 経由。ライト/ダークで値が入れ替わる。
        // チャンネル方式 (rgb(var(--x) / <alpha-value>)) なので bg-hull/50 等の
        // 不透明度修飾子もそのまま効く。void<hull<panel の順で面が持ち上がる。
        void: "rgb(var(--c-void) / <alpha-value>)",
        hull: "rgb(var(--c-hull) / <alpha-value>)",
        panel: "rgb(var(--c-panel) / <alpha-value>)",
        hairline: "rgb(var(--c-hairline) / <alpha-value>)",
        ink: "rgb(var(--c-ink) / <alpha-value>)",
        "ink-dim": "rgb(var(--c-ink-dim) / <alpha-value>)",
        "ink-faint": "rgb(var(--c-ink-faint) / <alpha-value>)",
        prog: {
          DEFAULT: "rgb(var(--c-prog) / <alpha-value>)",
          300: "rgb(var(--c-prog-300) / <alpha-value>)",
          500: "rgb(var(--c-prog) / <alpha-value>)",
          700: "#047857",
          900: "#064e3b",
        },
        act: {
          DEFAULT: "rgb(var(--c-act) / <alpha-value>)",
          300: "rgb(var(--c-act-300) / <alpha-value>)",
          700: "#b45309",
        },
        risk: {
          DEFAULT: "rgb(var(--c-risk) / <alpha-value>)",
          300: "rgb(var(--c-risk-300) / <alpha-value>)",
          700: "#be123c",
        },
        info: {
          DEFAULT: "rgb(var(--c-info) / <alpha-value>)",
          300: "rgb(var(--c-info-300) / <alpha-value>)",
          500: "#0ea5e9",
          700: "#0369a1",
        },
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
