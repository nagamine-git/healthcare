import type { SyncStatus as SyncT } from "../lib/api";

type Props = {
  sync: Record<string, SyncT>;
  onResync: () => void;
  pending?: boolean;
};

export function SyncStatus({ sync, onResync, pending }: Props) {
  const entries = Object.entries(sync);
  return (
    <div className="flex flex-col items-start justify-between gap-2 rounded-2xl bg-slate-900/40 px-4 py-3 text-xs text-slate-400 sm:flex-row sm:items-center">
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {entries.length === 0 ? (
          <span>同期履歴なし</span>
        ) : (
          entries.map(([source, status]) => (
            <span key={source} className={status.last_error ? "text-rose-400" : ""}>
              {source}: {formatTs(status.last_synced_at)}
              {status.last_error ? ` (失敗)` : ""}
            </span>
          ))
        )}
      </div>
      <button
        onClick={onResync}
        disabled={pending}
        className="rounded-full border border-slate-700 px-3 py-1 hover:bg-slate-800 disabled:opacity-50"
      >
        {pending ? "同期中..." : "Garmin 再同期"}
      </button>
    </div>
  );
}

function formatTs(ts: string | null): string {
  if (!ts) return "未同期";
  const date = new Date(ts);
  const diff = Date.now() - date.getTime();
  if (diff < 60_000) return "たった今";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分前`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 時間前`;
  return date.toLocaleString("ja-JP");
}
