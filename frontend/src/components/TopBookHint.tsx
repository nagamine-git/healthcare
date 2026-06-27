import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";

/** 未読のおすすめ本 TOP1 を具体提案(レバレッジ=弱点×重要度 が最大の本)。タップで羅針盤へ。 */
export function TopBookHint() {
  const q = useQuery({ queryKey: ["identity"], queryFn: api.identity, retry: false });
  const recs = q.data?.recommendations ?? [];
  const book = recs
    .filter((r) => r.kind === "book" && (r.category === "new" || r.category === "watchlist"))
    .sort((a, b) => b.score - a.score)[0];
  if (!book) return null;
  return (
    <button
      onClick={() => (window.location.hash = "#identity")}
      className="w-full rounded-lg border border-prog-700/60 bg-prog-900/15 p-2.5 text-left transition-colors hover:border-prog-500"
    >
      <span className="telemetry-label text-prog-300">📖 今日の1冊(未読のおすすめ)</span>
      <p className="mt-0.5 text-sm font-semibold text-ink">
        『{book.title}』{book.year ? `(${book.year})` : ""}
      </p>
      {book.reason && <p className="text-[11px] text-ink-faint">{book.reason}</p>}
    </button>
  );
}
