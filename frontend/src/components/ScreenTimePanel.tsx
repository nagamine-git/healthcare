import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Smartphone } from "lucide-react";
import { api } from "../lib/api";
import { fileToB64 } from "../lib/files";
import { LoadingState } from "./ui/cockpit";

/**
 * スマホ依存トラッキング。iOS スクリーンタイムのスクショ (Week+Day 複数可) を取り込み、
 * 日平均・トレンド・エンタメ比率・時間食いアプリを可視化。目標 (既定3h/日) 超過は赤。
 */

function hm(min: number | null | undefined): string {
  if (min == null) return "--";
  const h = Math.floor(min / 60);
  const m = Math.round(min % 60);
  return h > 0 ? `${h}h${m.toString().padStart(2, "0")}m` : `${m}m`;
}

const TREND = { up: "↑増加", down: "↓減少", flat: "→横ばい" } as const;

export function ScreenTimePanel() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["screentime"], queryFn: api.screentime });
  const imp = useMutation({
    mutationFn: (images: { image_base64: string; media_type: string }[]) =>
      api.screentimeImport(images),
    onSuccess: (data) => qc.setQueryData(["screentime"], data),
  });

  if (q.isLoading) return <LoadingState height="h-28" />;
  const s = q.data?.summary;

  const importBtn = (
    <label className="inline-block cursor-pointer rounded bg-prog-700 px-2.5 py-1 text-xs hover:bg-prog-500">
      スクショ取込(複数可)
      <input
        type="file"
        accept="image/*"
        multiple
        className="hidden"
        onChange={async (e) => {
          const files = Array.from(e.target.files ?? []);
          e.target.value = "";
          if (!files.length) return;
          const images = await Promise.all(
            files.map(async (f) => ({ image_base64: await fileToB64(f), media_type: f.type || "image/png" })),
          );
          imp.mutate(images);
        }}
      />
    </label>
  );

  return (
    <section className="space-y-2.5 rounded-xl bg-hull/40 p-4">
      <div className="flex items-center gap-1.5">
        <Smartphone size={14} className="text-info-300" />
        <span className="text-xs uppercase tracking-wider text-ink-dim">スマホ依存 (スクリーンタイム)</span>
        <span className="ml-auto">{importBtn}</span>
      </div>
      {imp.isPending && <p className="text-[11px] text-ink-faint">読取中…</p>}
      {imp.isError && <p className="text-[11px] text-risk">読取に失敗しました</p>}

      {!s || s.status === "no_data" ? (
        <p className="text-[11px] text-ink-faint">
          iOS「設定 → スクリーンタイム」の Week / Day 画面をスクショして取り込むと、
          日平均・トレンド・時間食いアプリを追跡します。
        </p>
      ) : (
        <>
          <div className="flex items-end gap-3">
            <div>
              <div className="text-[10px] text-ink-faint">最新日 ({s.latest_date})</div>
              <div className={`text-2xl font-bold tabular-nums ${s.over_target ? "text-risk" : "text-ink"}`}>
                {hm(s.latest_daily_min)}
              </div>
            </div>
            <div className="pb-1 text-[11px] text-ink-dim">
              7日平均 {hm(s.avg7_min)}
              {s.trend && <span className="ml-2 text-ink-faint">{TREND[s.trend]}</span>}
            </div>
          </div>

          {s.over_target && (
            <p className="text-[10px] text-risk/90">
              目標 {hm(s.target_daily_min)}/日 を超過。娯楽系を運動・読書・睡眠に置き換える余地。
            </p>
          )}

          {s.entertainment_share_pct != null && (
            <div>
              <div className="flex items-baseline justify-between text-[10px] text-ink-faint">
                <span>娯楽の割合</span>
                <span>{hm(s.entertainment_min)} · {s.entertainment_share_pct}%</span>
              </div>
              <div className="mt-1 h-1.5 rounded-full bg-hairline">
                <div
                  className="h-1.5 rounded-full bg-info"
                  style={{ width: `${Math.min(100, s.entertainment_share_pct)}%` }}
                />
              </div>
            </div>
          )}

          {(s.top_apps?.length ?? 0) > 0 && (
            <div className="space-y-0.5">
              <div className="text-[10px] font-semibold text-ink-dim">時間食いアプリ</div>
              {s.top_apps!.map((a, i) => (
                <div key={i} className="flex items-baseline justify-between text-[11px]">
                  <span className="min-w-0 flex-1 truncate text-ink-dim">{a.name}</span>
                  <span className="shrink-0 tabular-nums text-ink-faint">{hm(a.minutes)}</span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  );
}
