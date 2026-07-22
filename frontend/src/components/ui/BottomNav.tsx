import type { ReactNode } from "react";

/** SF シンボル風の線アイコン(currentColor 追従) */
const Icon = ({ d }: { d: string }) => (
  <svg viewBox="0 0 24 24" width={22} height={22} aria-hidden
    fill="none" stroke="currentColor"
    strokeWidth={1.9} strokeLinecap="round" strokeLinejoin="round">
    <path d={d} />
  </svg>
);

const ICONS: Record<string, ReactNode> = {
  home: <Icon d="M3 10.5 12 3l9 7.5M5 9.5V20a1 1 0 0 0 1 1h4v-6h4v6h4a1 1 0 0 0 1-1V9.5" />,
  compass: <Icon d="M12 3v2m0 14v2m9-9h-2M5 12H3m13.5-5.5-1.4 1.4M8.9 15.1l-1.4 1.4m0-9.9 1.4 1.4m6.2 6.2 1.4 1.4M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z" />,
  finance: <Icon d="M3 7h18v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V7Zm0 0 2.5-3h13L21 7M15 13h2" />,
  consult: <Icon d="M4 5h16a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H9l-4 4v-4H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1Z" />,
};

// 記録導線の統一 (Phase 2/3): 中央は「+」= クイック記録。庭は羅針盤タブへ統合。
const LEFT: { key: string; label: string; hash: string }[] = [
  { key: "home", label: "今日", hash: "" },
  { key: "compass", label: "羅針盤", hash: "#compass" },
];
const RIGHT: { key: string; label: string; hash: string }[] = [
  { key: "finance", label: "資産", hash: "#finance" },
  { key: "consult", label: "相談", hash: "#consult" },
];

/** アクティブは塗りピルで静かに持ち上げる。緑グローは廃止 (古びて見えるため)。 */
function NavButton({ it, current }: { it: { key: string; label: string; hash: string }; current: string }) {
  const active = it.key === current;
  return (
    <button
      onClick={() => {
        window.location.hash = it.hash;
      }}
      aria-label={it.label}
      aria-current={active ? "page" : undefined}
      className={`press flex flex-1 flex-col items-center gap-0.5 rounded-2xl py-1.5 transition-colors ${
        active ? "bg-ink/[0.07] text-ink" : "text-ink-faint hover:text-ink-dim"
      }`}
    >
      {ICONS[it.key]}
      <span className="text-[10px] font-semibold tracking-tight">{it.label}</span>
    </button>
  );
}

/**
 * 全画面に常設の浮遊ナビ。端から浮かせたカプセルで iOS 風に。
 * 中央の + はどこからでも 2 タップで記録できる主導線 — ここだけ主役色 (amber)。
 */
export function BottomNav({ current, onQuickLog }: { current: string; onQuickLog: () => void }) {
  return (
    <div
      className="pointer-events-none fixed inset-x-0 bottom-0 z-40 flex justify-center"
      style={{ paddingBottom: "calc(env(safe-area-inset-bottom) + 10px)" }}
    >
      <nav className="pointer-events-auto relative mx-4 flex w-full max-w-md items-center gap-1 rounded-[26px] border border-hairline bg-panel/85 px-2 py-1.5 shadow-float backdrop-blur-2xl">
        {LEFT.map((it) => <NavButton key={it.key} it={it} current={current} />)}

        {/* 中央 +: カプセルから少し持ち上げた記録ボタン。地色のリングで浮遊感を出す。 */}
        <div className="flex shrink-0 items-center justify-center px-1">
          <button
            onClick={onQuickLog}
            aria-label="クイック記録"
            className="press -mt-6 grid place-items-center rounded-full bg-act text-void shadow-glow-act ring-4 ring-panel transition hover:bg-act-300 active:scale-95"
            style={{ height: "3.25rem", width: "3.25rem" }}
          >
            <svg viewBox="0 0 24 24" width={24} height={24} aria-hidden fill="none"
              stroke="currentColor" strokeWidth={2.4} strokeLinecap="round">
              <path d="M12 5v14M5 12h14" />
            </svg>
          </button>
        </div>

        {RIGHT.map((it) => <NavButton key={it.key} it={it} current={current} />)}
      </nav>
    </div>
  );
}
