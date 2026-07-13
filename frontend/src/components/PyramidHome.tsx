import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../lib/api";
import { achState, type AchState } from "../lib/achievement";

/**
 * 幸せに生きる — 4本柱(資産/心身/成長/つながり)のホーム。
 * Apple 製品のようにホームはとことんシンプル(4カード)にし、タップで段階的に開く
 * (progressive disclosure)。詳細な全パネルは下層に温存(=解像度は落とさない)。
 * 既存の /api/life(心身・成長)と /api/finance(資産)を再利用。つながりは手帳(話した人)から(準備中)。
 */

const DOT: Record<AchState, string> = {
  good: "bg-prog-500", warn: "bg-act", bad: "bg-risk", off: "bg-panel",
};
const TXT: Record<AchState, string> = {
  good: "text-prog-300", warn: "text-act-300", bad: "text-risk", off: "text-ink-faint",
};

type Sub = { label: string; achievement: number | null; detail?: string | null };
type Pillar = { key: string; label: string; achievement: number | null; note?: string; subs: Sub[]; href?: string };

export function PyramidHome() {
  const life = useQuery({ queryKey: ["life"], queryFn: api.life });
  const fin = useQuery({ queryKey: ["finance"], queryFn: api.finance, retry: false });
  const [open, setOpen] = useState<string | null>(null);
  if (life.isLoading || !life.data) return null;

  const domains = life.data.domains;
  const d = (k: string) => domains.find((x) => x.key === k);
  const mean = (keys: string[]): number | null => {
    const v = keys.map((k) => d(k)?.achievement).filter((x): x is number => x != null);
    return v.length ? Math.round(v.reduce((a, b) => a + b, 0) / v.length) : null;
  };
  const sub = (k: string, label?: string): Sub => ({
    label: label ?? d(k)?.label ?? k, achievement: d(k)?.achievement ?? null, detail: d(k)?.detail,
  });

  // 資産: advisor の警告数から粗い達成度(warn 1つ -25)
  const adv = fin.data?.advisor;
  let assetAch: number | null = null;
  let assetNote: string | undefined;
  if (adv?.has_data) {
    const warn = adv.diagnosis.filter((x) => x.level === "warn").length;
    assetAch = Math.max(0, 100 - 25 * warn);
    assetNote = adv.moves[0]?.text ?? "資産は安定";
  } else {
    assetNote = "資産・入出金・生活状況を入れると診断";
  }

  const pillars: Pillar[] = [
    { key: "asset", label: "資産", achievement: assetAch, note: assetNote, href: "#finance", subs: [] },
    { key: "mind_body", label: "心身", achievement: mean(["health", "meditation"]),
      subs: [sub("health", "体(睡眠/運動/栄養…)"), sub("meditation", "心(瞑想)")] },
    { key: "growth", label: "成長", achievement: mean(["learning", "work", "speech"]),
      subs: [sub("work", "仕事"), sub("learning", "学習"), sub("speech", "発話")] },
    { key: "connection", label: "つながり", achievement: null,
      note: "手帳の「話した人」から(準備中)", href: "#journal", subs: [] },
  ];

  const openPillar = pillars.find((x) => x.key === open);

  return (
    <section className="rounded-2xl bg-hull/50 p-3 ring-1 ring-panel">
      <div className="mb-2 flex items-baseline justify-between">
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-ink-dim">幸せに生きる</h2>
        {life.data.life_score != null && (
          <span className="text-[11px] tabular-nums text-ink-faint">ライフ {life.data.life_score}</span>
        )}
      </div>
      <div className="grid grid-cols-2 gap-2">
        {pillars.map((p) => {
          const st = achState(p.achievement);
          return (
            <button
              key={p.key}
              onClick={() => setOpen(open === p.key ? null : p.key)}
              className={`rounded-xl bg-void/40 p-3 text-left transition active:scale-[0.99] ${
                open === p.key ? "ring-1 ring-panel" : ""
              }`}
            >
              <div className="flex items-center gap-1.5">
                <span className={`h-2 w-2 rounded-full ${DOT[st]}`} />
                <span className="text-[13px] font-medium text-ink">{p.label}</span>
              </div>
              <div className={`mt-1 text-2xl font-light tabular-nums ${TXT[st]}`}>
                {p.achievement != null ? p.achievement : "—"}
              </div>
              {p.note && <div className="mt-0.5 line-clamp-2 text-[10px] leading-tight text-ink-faint">{p.note}</div>}
            </button>
          );
        })}
      </div>

      {openPillar && (
        <div className="mt-2 space-y-1 rounded-xl bg-void/30 p-2.5">
          {openPillar.subs.map((s) => {
            const st = achState(s.achievement);
            return (
              <div key={s.label} className="flex items-baseline justify-between gap-2 text-[12px]">
                <span className="min-w-0 flex-1 truncate text-ink-dim">
                  {s.label}
                  {s.detail && <span className="text-ink-faint"> · {s.detail}</span>}
                </span>
                <span className={`shrink-0 tabular-nums ${TXT[st]}`}>
                  {s.achievement != null ? s.achievement : "—"}
                </span>
              </div>
            );
          })}
          {openPillar.subs.length === 0 && openPillar.note && (
            <p className="text-[11px] text-ink-faint">{openPillar.note}</p>
          )}
          {openPillar.href && (
            <a href={openPillar.href} className="mt-1 inline-block text-[11px] text-info-300">
              詳細へ →
            </a>
          )}
        </div>
      )}
    </section>
  );
}
