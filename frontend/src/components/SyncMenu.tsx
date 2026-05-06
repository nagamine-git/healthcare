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
        className="rounded-full border border-slate-700 bg-slate-900/60 px-3 py-1 text-xs text-slate-300 hover:bg-slate-800"
      >
        ⟳ 同期
      </button>
      {open && (
        <div className="absolute right-0 top-full z-20 mt-1 w-64 origin-top-right rounded-xl border border-slate-800 bg-slate-900 p-1 shadow-xl">
          {lastSyncedLabel && (
            <div className="px-3 py-1.5 text-[10px] text-slate-500">{lastSyncedLabel}</div>
          )}
          {visible.map((it, i) => (
            <button
              key={i}
              onClick={() => {
                setOpen(false);
                it.onClick();
              }}
              disabled={it.pending}
              className="block w-full rounded-lg px-3 py-2 text-left text-xs text-slate-200 hover:bg-slate-800 disabled:opacity-50"
            >
              <div className="flex items-center justify-between">
                <span>{it.label}</span>
                {it.pending && <span className="text-slate-500">…</span>}
              </div>
              {it.description && (
                <div className="text-[10px] text-slate-500">{it.description}</div>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
