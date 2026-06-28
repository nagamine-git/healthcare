import { useEffect, useRef, useState } from "react";

type Item = {
  label: string;
  onClick: () => void;
  description?: string;
  pending?: boolean;
  hidden?: boolean;
};

type Props = {
  items: Item[];
  lastSyncedLabel?: string;
};

/** ヘッダ右の「同期」プルダウン。データ取得・スコア再計算・LLM再生成を集約。 */
export function SyncMenu({ items, lastSyncedLabel }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    if (open) document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  const visible = items.filter((i) => !i.hidden);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="rounded-full border border-hairline bg-hull/60 px-3 py-1 text-xs text-ink-dim hover:bg-panel"
      >
        ⟳ 同期
      </button>
      {open && (
        <div className="absolute right-0 top-full z-20 mt-1 w-64 origin-top-right rounded-xl border border-panel bg-hull p-1 shadow-xl">
          {lastSyncedLabel && (
            <div className="px-3 py-1.5 text-[10px] text-ink-faint">{lastSyncedLabel}</div>
          )}
          {visible.map((it, i) => (
            <button
              key={i}
              onClick={() => {
                setOpen(false);
                it.onClick();
              }}
              disabled={it.pending}
              className="block w-full rounded-lg px-3 py-2 text-left text-xs text-ink hover:bg-panel disabled:opacity-50"
            >
              <div className="flex items-center justify-between">
                <span>{it.label}</span>
                {it.pending && <span className="text-ink-faint">…</span>}
              </div>
              {it.description && (
                <div className="text-[10px] text-ink-faint">{it.description}</div>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
