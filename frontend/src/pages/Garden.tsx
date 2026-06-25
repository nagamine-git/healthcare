import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type GardenGridCell } from "../lib/api";

const LEVEL_BG = [
  "bg-slate-800",
  "bg-emerald-900",
  "bg-emerald-700",
  "bg-emerald-500",
  "bg-emerald-300",
];
const KIND_LABEL: Record<string, string> = {
  coding: "コーディング",
  exercise: "運動",
  meditation: "瞑想",
  journaling: "ジャーナリング",
  reflection: "内省",
};

function ContributionGrid({ grid }: { grid: GardenGridCell[] }) {
  const byDate = new Map(grid.map((c) => [c.date, c]));
  const last = grid.length ? grid[grid.length - 1].date : new Date().toISOString().slice(0, 10);
  const end = new Date(last + "T00:00:00");
  const days: string[] = [];
  for (let i = 370; i >= 0; i--) {
    const d = new Date(end);
    d.setDate(end.getDate() - i);
    days.push(d.toISOString().slice(0, 10));
  }
  const weeks: string[][] = [];
  for (let i = 0; i < days.length; i += 7) weeks.push(days.slice(i, i + 7));
  return (
    <div className="flex gap-[3px] overflow-x-auto pb-2">
      {weeks.map((week, wi) => (
        <div key={wi} className="flex flex-col gap-[3px]">
          {week.map((d) => {
            const cell = byDate.get(d);
            const level = cell?.level ?? 0;
            const kinds = cell
              ? Object.keys(cell.contributions)
                  .map((k) => KIND_LABEL[k] ?? k)
                  .join(", ") || "—"
              : "—";
            return (
              <div
                key={d}
                title={`${d}: ${kinds}`}
                className={`h-[11px] w-[11px] rounded-sm ${LEVEL_BG[level]}`}
              />
            );
          })}
        </div>
      ))}
    </div>
  );
}

export function GardenPage({ onBack }: { onBack: () => void }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["garden"], queryFn: api.garden });
  const logMut = useMutation({
    mutationFn: (kind: string) => api.gardenLog(kind),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["garden"] }),
  });
  const [user, setUser] = useState("");
  const [token, setToken] = useState("");
  const cfgMut = useMutation({
    mutationFn: () => api.gardenConfig(user, token),
    onSuccess: () => {
      setToken("");
      qc.invalidateQueries({ queryKey: ["garden"] });
    },
  });

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4">
      <button onClick={onBack} className="text-sm text-slate-400">
        ← 戻る
      </button>
      <h1 className="text-xl font-bold">理想の庭</h1>
      {q.isLoading && <p>読み込み中…</p>}
      {q.isError && <p className="text-red-400">取得に失敗しました</p>}
      {q.data && (
        <>
          <div className="rounded-lg bg-slate-900 p-4">
            <div className="mb-2 flex items-baseline justify-between">
              <span className="text-sm text-slate-400">連続</span>
              <span className="text-2xl font-bold text-emerald-400">{q.data.streak}日</span>
            </div>
            <ContributionGrid grid={q.data.grid} />
          </div>

          {q.data.weakest_hint && (
            <div className="rounded-lg bg-slate-900 p-4 text-sm">
              <span className="text-slate-400">今日効く行動: </span>
              <span className="font-semibold">{q.data.weakest_hint.name}</span>
              <span className="text-slate-400"> に効く </span>
              {q.data.weakest_hint.kinds.map((k) => KIND_LABEL[k] ?? k).join("・")}
              <span className="text-slate-400"> が濃く出ます</span>
            </div>
          )}

          <div className="rounded-lg bg-slate-900 p-4">
            <p className="mb-2 text-sm text-slate-400">今日の行動を記録</p>
            <div className="flex flex-wrap gap-2">
              {q.data.catalog
                .filter((c) => c.source === "manual")
                .map((c) => (
                  <button
                    key={c.kind}
                    disabled={logMut.isPending}
                    onClick={() => logMut.mutate(c.kind)}
                    className="rounded-full bg-emerald-700 px-3 py-1 text-sm hover:bg-emerald-600 disabled:opacity-50"
                  >
                    + {KIND_LABEL[c.kind] ?? c.kind}
                  </button>
                ))}
            </div>
            {q.data.today.actions.length > 0 && (
              <p className="mt-2 text-xs text-slate-500">
                今日: {q.data.today.actions.map((k) => KIND_LABEL[k] ?? k).join("・")}
              </p>
            )}
          </div>

          <div className="rounded-lg bg-slate-900 p-4">
            <p className="mb-2 text-sm text-slate-400">
              GitHub 連携 {q.data.github.connected ? `(${q.data.github.username})` : "(未接続)"}
            </p>
            <div className="flex flex-col gap-2 sm:flex-row">
              <input
                value={user}
                onChange={(e) => setUser(e.target.value)}
                placeholder="username"
                className="rounded bg-slate-800 px-2 py-1 text-sm"
              />
              <input
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder="personal access token"
                type="password"
                className="flex-1 rounded bg-slate-800 px-2 py-1 text-sm"
              />
              <button
                disabled={cfgMut.isPending || !token}
                onClick={() => cfgMut.mutate()}
                className="rounded bg-slate-700 px-3 py-1 text-sm hover:bg-slate-600 disabled:opacity-50"
              >
                保存
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
