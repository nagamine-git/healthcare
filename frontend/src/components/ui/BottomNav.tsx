const ITEMS: { key: string; label: string; hash: string }[] = [
  { key: "home", label: "ホーム", hash: "" },
  { key: "life", label: "人生", hash: "#life" },
  { key: "garden", label: "庭", hash: "#garden" },
  { key: "identity", label: "羅針盤", hash: "#identity" },
  { key: "becoming", label: "歩み", hash: "#becoming" },
];

/** 全画面に常設のナビ。どこからでも 1 タップで主要機能へ。 */
export function BottomNav({ current }: { current: string }) {
  return (
    <nav
      className="fixed inset-x-0 bottom-0 z-40 border-t border-hairline bg-void/90 backdrop-blur"
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
    >
      <div className="mx-auto flex max-w-2xl">
        {ITEMS.map((it) => {
          const active = it.key === current;
          return (
            <button
              key={it.key}
              onClick={() => {
                window.location.hash = it.hash;
              }}
              className={`flex-1 py-3 text-[11px] transition-colors ${
                active ? "text-prog-300" : "text-ink-faint hover:text-ink-dim"
              }`}
            >
              <span
                className={`mx-auto mb-1 block h-0.5 w-5 rounded-full ${
                  active ? "bg-prog-500" : "bg-transparent"
                }`}
              />
              {it.label}
            </button>
          );
        })}
      </div>
    </nav>
  );
}
