import type { ReactNode } from "react";

/** SF シンボル風の線アイコン(currentColor 追従) */
const Icon = ({ d }: { d: string }) => (
  <svg viewBox="0 0 24 24" width={24} height={24} aria-hidden
    fill="none" stroke="currentColor"
    strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
    <path d={d} />
  </svg>
);

const ICONS: Record<string, ReactNode> = {
  home: <Icon d="M3 10.5 12 3l9 7.5M5 9.5V20a1 1 0 0 0 1 1h4v-6h4v6h4a1 1 0 0 0 1-1V9.5" />,
  life: <Icon d="M12 21C7 17.5 3 14 3 9.5A4.5 4.5 0 0 1 12 7a4.5 4.5 0 0 1 9 2.5C21 14 17 17.5 12 21Z" />,
  garden: <Icon d="M12 22V12m0 0c0-3 2-5 5-5 0 3-2 5-5 5Zm0 0C9 12 7 10 7 7c3 0 5 2 5 5Z" />,
  identity: <Icon d="M12 3v2m0 14v2m9-9h-2M5 12H3m13.5-5.5-1.4 1.4M8.9 15.1l-1.4 1.4m0-9.9 1.4 1.4m6.2 6.2 1.4 1.4M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z" />,
  becoming: <Icon d="M4 19V5m0 14h16M4 19l5-6 4 3 7-9" />,
  finance: <Icon d="M3 7h18v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V7Zm0 0 2.5-3h13L21 7M15 13h2" />,
};

const ITEMS: { key: string; label: string; hash: string }[] = [
  { key: "home", label: "ホーム", hash: "" },
  { key: "life", label: "人生", hash: "#life" },
  { key: "garden", label: "庭", hash: "#garden" },
  { key: "identity", label: "羅針盤", hash: "#identity" },
  { key: "becoming", label: "歩み", hash: "#becoming" },
  { key: "finance", label: "資産", hash: "#finance" },
];

/** 全画面に常設のナビ。どこからでも 1 タップで主要機能へ。 */
export function BottomNav({ current }: { current: string }) {
  return (
    <nav
      className="fixed inset-x-0 bottom-0 z-40 border-t border-white/[0.06] bg-void/80 backdrop-blur-xl"
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
    >
      <div className="mx-auto flex max-w-2xl px-1">
        {ITEMS.map((it) => {
          const active = it.key === current;
          return (
            <button
              key={it.key}
              onClick={() => {
                window.location.hash = it.hash;
              }}
              aria-label={it.label}
              aria-current={active ? "page" : undefined}
              className={`press flex flex-1 flex-col items-center gap-0.5 pb-1.5 pt-2 transition-colors ${
                active ? "text-prog-300" : "text-ink-faint hover:text-ink-dim"
              }`}
            >
              <span className={active ? "drop-shadow-[0_0_8px_rgba(110,231,183,0.35)]" : ""}>
                {ICONS[it.key]}
              </span>
              <span className="text-[10px] font-medium tracking-tight">{it.label}</span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}
