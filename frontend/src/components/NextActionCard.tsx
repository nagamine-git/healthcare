import { useQuery } from "@tanstack/react-query";
import { Crosshair } from "lucide-react";
import { api } from "../lib/api";
import type { NextActionItem } from "../lib/api";
import { LoadingState } from "./ui/cockpit";

/**
 * 「いまコレ」— サービス内外の全選択肢 (装着/仮眠/水/プロテイン/記録/資産/学習/就寝準備…)
 * から、今この瞬間に最も価値のある1手を提示する。バックエンドの決定論的ランキング
 * (/api/next-action) なので瞬時・毎分更新。タップで該当画面 or クイック記録へ直行。
 */

function follow(link: string | null) {
  if (!link) return;
  if (link === "quicklog") {
    window.dispatchEvent(new CustomEvent("open-quicklog"));
  } else {
    window.location.hash = link;
  }
}

function Primary({ a }: { a: NextActionItem }) {
  const clickable = a.link != null;
  return (
    <button
      onClick={() => follow(a.link)}
      disabled={!clickable}
      className={`w-full rounded-xl border border-act-700/50 bg-act/10 p-3.5 text-left shadow-glow-act transition ${
        clickable ? "active:scale-[0.99] hover:border-act-700" : "cursor-default"
      }`}
    >
      <div className="flex items-center gap-1.5">
        <Crosshair size={13} className="text-act-300" />
        <span className="text-[10px] font-semibold uppercase tracking-wider text-act-300">
          いまコレ
        </span>
        {clickable && <span className="ml-auto text-[10px] text-ink-faint">タップで移動 →</span>}
      </div>
      <div className="mt-1.5 text-[15px] font-semibold leading-snug text-ink">{a.title}</div>
      <div className="mt-1 text-[11px] leading-relaxed text-ink-dim">{a.why}</div>
    </button>
  );
}

export function NextActionCard() {
  const q = useQuery({
    queryKey: ["next-action"],
    queryFn: api.nextAction,
    refetchInterval: 5 * 60_000, // 時刻依存ルールが多いので5分毎に鮮度を保つ
  });
  if (q.isLoading) return <LoadingState height="h-20" />;
  if (!q.data) return null;
  const { primary, others } = q.data;

  return (
    <div className="space-y-1.5">
      <Primary a={primary} />
      {others.length > 0 && (
        <div className="flex flex-wrap gap-1.5 px-0.5">
          {others.map((o) => (
            <button
              key={o.key}
              onClick={() => follow(o.link)}
              title={o.why}
              className={`rounded-full bg-panel px-2.5 py-1 text-[11px] text-ink-dim transition hover:text-ink ${
                o.link ? "active:scale-95" : "cursor-default"
              }`}
            >
              {o.title}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
