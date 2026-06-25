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

function kindLabel(k: string): string {
  return KIND_LABEL[k] ?? k;
}

function syncErrorMessage(reason?: string): string {
  switch (reason) {
    case "unauthorized":
      return "同期失敗: GitHub にトークンが拒否されました(401/403)。read:user スコープの有効な classic トークンを入れ直してください。";
    case "no_credentials":
      return "同期失敗: トークンが未設定です。";
    default:
      return "同期失敗: GitHub への接続に失敗しました。少し待って再試行してください。";
  }
}

function ContributionGrid({
  grid,
  selected,
  onSelect,
}: {
  grid: GardenGridCell[];
  selected: string | null;
  onSelect: (date: string) => void;
}) {
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
            const isSel = d === selected;
            return (
              <button
                key={d}
                type="button"
                onClick={() => onSelect(d)}
                title={d}
                className={`h-[11px] w-[11px] rounded-sm ${LEVEL_BG[level]} ${
                  isSel ? "ring-2 ring-white" : ""
                }`}
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
  const invalidate = () => qc.invalidateQueries({ queryKey: ["garden"] });

  const logMut = useMutation({
    mutationFn: (kind: string) => api.gardenLog(kind),
    onSuccess: invalidate,
  });
  const delMut = useMutation({
    mutationFn: (id: number) => api.gardenDeleteLog(id),
    onSuccess: invalidate,
  });
  const syncMut = useMutation({ mutationFn: () => api.gardenSync(), onSuccess: invalidate });

  const [user, setUser] = useState("");
  const [token, setToken] = useState("");
  const cfgMut = useMutation({
    mutationFn: () => api.gardenConfig(user, token),
    onSuccess: async () => {
      setToken("");
      await syncMut.mutateAsync(); // 接続直後に過去1年分を取り込む
      invalidate();
    },
  });

  const [selected, setSelected] = useState<string | null>(null);
  const selectedCell = q.data?.grid.find((c) => c.date === selected) ?? null;

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
            <ContributionGrid grid={q.data.grid} selected={selected} onSelect={setSelected} />
            {selected && (
              <div className="mt-2 border-t border-slate-800 pt-2 text-sm">
                <span className="text-slate-400">{selected}: </span>
                {selectedCell && Object.keys(selectedCell.contributions).length > 0 ? (
                  <span>
                    {Object.entries(selectedCell.contributions)
                      .map(([k, v]) => `${kindLabel(k)} (+${v.toFixed(1)})`)
                      .join("・")}
                    <span className="ml-1 text-slate-500">= {selectedCell.intensity.toFixed(1)}</span>
                  </span>
                ) : (
                  <span className="text-slate-500">記録なし</span>
                )}
              </div>
            )}
          </div>

          {q.data.weakest_hint && (
            <div className="rounded-lg bg-slate-900 p-4 text-sm">
              <span className="text-slate-400">今日効く行動: </span>
              <span className="font-semibold">{q.data.weakest_hint.name}</span>
              <span className="text-slate-400"> に効く </span>
              {q.data.weakest_hint.kinds.map(kindLabel).join("・")}
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
                    + {kindLabel(c.kind)}
                  </button>
                ))}
            </div>
          </div>

          <div className="rounded-lg bg-slate-900 p-4">
            <p className="mb-2 text-sm text-slate-400">記録履歴</p>
            {q.data.recent_logs.length === 0 ? (
              <p className="text-xs text-slate-500">まだ記録がありません</p>
            ) : (
              <ul className="space-y-1">
                {q.data.recent_logs.map((log) => (
                  <li
                    key={log.id}
                    className="flex items-center justify-between border-b border-slate-800/60 py-1 text-sm last:border-0"
                  >
                    <span>
                      <span className="tabular-nums text-slate-500">
                        {log.ts.slice(0, 16).replace("T", " ")}
                      </span>{" "}
                      {kindLabel(log.kind)}
                      {log.note && <span className="text-slate-400"> — {log.note}</span>}
                    </span>
                    {log.source === "manual" && (
                      <button
                        disabled={delMut.isPending}
                        onClick={() => delMut.mutate(log.id)}
                        className="ml-2 text-xs text-slate-500 hover:text-red-400 disabled:opacity-50"
                      >
                        削除
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="rounded-lg bg-slate-900 p-4">
            <div className="mb-2 flex items-center justify-between">
              <p className="text-sm text-slate-400">GitHub 連携</p>
              {q.data.github.connected ? (
                <span className="text-sm font-semibold text-emerald-400">
                  ✓ 接続済み: {q.data.github.username}
                </span>
              ) : (
                <span className="text-sm text-slate-500">未接続</span>
              )}
            </div>
            <div className="flex flex-col gap-2 sm:flex-row">
              <input
                value={user}
                onChange={(e) => setUser(e.target.value)}
                placeholder={q.data.github.username ?? "username"}
                className="rounded bg-slate-800 px-2 py-1 text-sm"
              />
              <input
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder="personal access token (read:user / repo)"
                type="password"
                className="flex-1 rounded bg-slate-800 px-2 py-1 text-sm"
              />
              <button
                disabled={cfgMut.isPending || syncMut.isPending || !token}
                onClick={() => cfgMut.mutate()}
                className="rounded bg-slate-700 px-3 py-1 text-sm hover:bg-slate-600 disabled:opacity-50"
              >
                {cfgMut.isPending || syncMut.isPending ? "同期中…" : "保存して同期"}
              </button>
            </div>
            {q.data.github.connected && (
              <button
                disabled={syncMut.isPending}
                onClick={() => syncMut.mutate()}
                className="mt-2 text-xs text-emerald-400 hover:text-emerald-300 disabled:opacity-50"
              >
                {syncMut.isPending ? "同期中…" : "今すぐ同期(過去1年を再取得)"}
              </button>
            )}
            {syncMut.data && !syncMut.isPending && (
              syncMut.data.status === "ok" ? (
                <p className="mt-1 text-xs text-slate-500">
                  同期完了{syncMut.data.recomputed_days ? `(${syncMut.data.recomputed_days}日分)` : ""}
                </p>
              ) : (
                <p className="mt-1 text-xs text-red-400">{syncErrorMessage(syncMut.data.reason)}</p>
              )
            )}
          </div>
        </>
      )}
    </div>
  );
}
