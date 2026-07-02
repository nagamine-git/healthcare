import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type GardenGridCell } from "../lib/api";
import { gardenCellStyle } from "../lib/gardenColor";
import { kindLabel } from "../lib/labels";
import { TopBookHint } from "../components/TopBookHint";

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

  const monthLabel = (week: string[], wi: number): string => {
    const first = new Date(week[0] + "T00:00:00");
    const prev = wi > 0 ? new Date(weeks[wi - 1][0] + "T00:00:00") : null;
    if (!prev || first.getMonth() !== prev.getMonth()) return `${first.getMonth() + 1}月`;
    return "";
  };

  return (
    <div className="overflow-x-auto pb-2">
      {/* 月ラベル(週列に合わせて表示) */}
      <div className="mb-1 flex gap-[3px]">
        {weeks.map((week, wi) => (
          <div
            key={wi}
            className="w-[11px] shrink-0 overflow-visible whitespace-nowrap text-[8px] text-ink-faint"
          >
            {monthLabel(week, wi)}
          </div>
        ))}
      </div>
      {/* 草マス本体 */}
      <div className="flex gap-[3px]">
        {weeks.map((week, wi) => (
          <div key={wi} className="flex flex-col gap-[3px]">
            {week.map((d) => {
              const cell = byDate.get(d);
              const level = cell?.level ?? 0;
              const style = gardenCellStyle(level, cell?.focus ?? 0);
              const isSel = d === selected;
              return (
                <button
                  key={d}
                  type="button"
                  onClick={() => onSelect(d)}
                  title={d}
                  style={style ?? undefined}
                  className={`h-[11px] w-[11px] rounded-sm ${style ? "" : "bg-panel"} ${
                    isSel ? "ring-2 ring-white" : ""
                  }`}
                />
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

export function GardenPage({ onBack, embedded }: { onBack: () => void; embedded?: boolean }) {
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
    <div
      className={
        embedded
          ? "space-y-4"
          : "safe-area-top safe-area-x pb-nav mx-auto max-w-3xl space-y-4"
      }
    >
      {!embedded && (
        <>
          <button onClick={onBack} className="text-sm text-ink-dim">
            ← 戻る
          </button>
          <h1 className="text-xl font-bold">理想の庭</h1>
        </>
      )}
      {q.isLoading && <p>読み込み中…</p>}
      {q.isError && <p className="text-risk">取得に失敗しました</p>}
      {q.data && (
        <>
          <div className="rounded-lg bg-hull p-4">
            <div className="mb-2 flex items-baseline justify-between">
              <span className="text-sm text-ink-dim">連続</span>
              <span className="text-2xl font-bold text-prog-300">{q.data.streak}日</span>
            </div>
            <ContributionGrid grid={q.data.grid} selected={selected} onSelect={setSelected} />
            {/* 凡例: 色=重点度 / 濃さ=量 の2軸 */}
            <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[9px] text-ink-faint">
              <span className="flex items-center gap-1">
                <span className="h-2 w-2 rounded-sm" style={gardenCellStyle(4, 0) ?? undefined} />
                白=今は重点でない努力
              </span>
              <span className="flex items-center gap-1">
                <span className="h-2 w-2 rounded-sm" style={gardenCellStyle(4, 1) ?? undefined} />
                緑=重点(盲点)に効く
              </span>
              <span>濃さ=量</span>
            </div>
            {selected && (
              <div className="mt-2 border-t border-hairline pt-2 text-sm">
                <span className="text-ink-dim">{selected}: </span>
                {selectedCell && Object.keys(selectedCell.contributions).length > 0 ? (
                  <span>
                    {Object.entries(selectedCell.contributions)
                      .map(([k, v]) => `${kindLabel(k)} (+${v.toFixed(1)})`)
                      .join("・")}
                    <span className="ml-1 text-ink-faint">= {selectedCell.intensity.toFixed(1)}</span>
                    <span className="ml-1 text-ink-faint">
                      / 重点度 {Math.round(selectedCell.focus * 100)}%
                    </span>
                  </span>
                ) : (
                  <span className="text-ink-faint">記録なし</span>
                )}
              </div>
            )}
          </div>

          {q.data.weakest_hint && (
            <div className="rounded-lg bg-hull p-4 text-sm">
              <span className="text-ink-dim">今日効く行動: </span>
              <span className="font-semibold">{q.data.weakest_hint.name}</span>
              <span className="text-ink-dim"> に効く </span>
              {q.data.weakest_hint.kinds.map(kindLabel).join("・")}
              <span className="text-ink-dim"> が濃く出ます</span>
            </div>
          )}

          <TopBookHint />

          <div className="rounded-lg bg-hull p-4">
            <p className="mb-2 text-sm text-ink-dim">
              今日の行動を記録 <span className="text-xs text-ink-faint">(緑=今日効く / 白=その他)</span>
            </p>
            <div className="flex flex-wrap gap-2">
              {(() => {
                const effSet = new Set(q.data.weakest_hint?.kinds ?? []);
                const hasFocus = effSet.size > 0;
                const logged = new Set(Object.keys(q.data.today.contributions ?? {}));
                const manual = q.data.catalog.filter((c) => c.source === "manual");
                const sorted = [...manual].sort(
                  (a, b) => Number(effSet.has(b.kind)) - Number(effSet.has(a.kind)),
                );
                return sorted.map((c) => {
                  const eff = !hasFocus || effSet.has(c.kind);
                  const done = logged.has(c.kind);
                  const cls = eff
                    ? done
                      ? "bg-prog-500 text-void"
                      : "bg-prog-700 text-ink hover:bg-prog-500"
                    : done
                      ? "border border-prog-700 text-prog-300"
                      : "border border-hairline text-ink-faint hover:text-ink-dim";
                  return (
                    <button
                      key={c.kind}
                      disabled={logMut.isPending}
                      onClick={() => logMut.mutate(c.kind)}
                      className={`rounded-full px-3 py-1 text-sm transition-colors disabled:opacity-50 ${cls}`}
                    >
                      {done ? "✓ " : "+ "}
                      {kindLabel(c.kind)}
                    </button>
                  );
                });
              })()}
            </div>
          </div>

          <div className="rounded-lg bg-hull p-4">
            <p className="mb-2 text-sm text-ink-dim">記録履歴</p>
            {q.data.recent_logs.length === 0 ? (
              <p className="text-xs text-ink-faint">まだ記録がありません</p>
            ) : (
              <ul className="space-y-1">
                {q.data.recent_logs.map((log) => (
                  <li
                    key={log.id}
                    className="flex items-center justify-between border-b border-hairline/60 py-1 text-sm last:border-0"
                  >
                    <span>
                      <span className="tabular-nums text-ink-faint">
                        {log.ts.slice(0, 16).replace("T", " ")}
                      </span>{" "}
                      {kindLabel(log.kind)}
                      {log.note && <span className="text-ink-dim"> — {log.note}</span>}
                    </span>
                    {["manual", "journal", "book_tracker"].includes(log.source) && (
                      <button
                        disabled={delMut.isPending}
                        onClick={() => delMut.mutate(log.id)}
                        className="ml-2 text-xs text-ink-faint hover:text-risk disabled:opacity-50"
                      >
                        削除
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="rounded-lg bg-hull p-4">
            <div className="mb-2 flex items-center justify-between">
              <p className="text-sm text-ink-dim">GitHub 連携</p>
              {q.data.github.connected ? (
                <span className="text-sm font-semibold text-prog-300">
                  ✓ 接続済み: {q.data.github.username}
                </span>
              ) : (
                <span className="text-sm text-ink-faint">未接続</span>
              )}
            </div>
            <div className="flex flex-col gap-2 sm:flex-row">
              <input
                value={user}
                onChange={(e) => setUser(e.target.value)}
                placeholder={q.data.github.username ?? "username"}
                className="rounded bg-panel px-2 py-1 text-sm"
              />
              <input
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder="personal access token (read:user / repo)"
                type="password"
                className="flex-1 rounded bg-panel px-2 py-1 text-sm"
              />
              <button
                disabled={cfgMut.isPending || syncMut.isPending || !token}
                onClick={() => cfgMut.mutate()}
                className="rounded bg-panel px-3 py-1 text-sm hover:bg-panel disabled:opacity-50"
              >
                {cfgMut.isPending || syncMut.isPending ? "同期中…" : "保存して同期"}
              </button>
            </div>
            {q.data.github.connected && (
              <button
                disabled={syncMut.isPending}
                onClick={() => syncMut.mutate()}
                className="mt-2 text-xs text-prog-300 hover:text-prog-300 disabled:opacity-50"
              >
                {syncMut.isPending ? "同期中…" : "今すぐ同期(過去1年を再取得)"}
              </button>
            )}
            {syncMut.data && !syncMut.isPending && (
              syncMut.data.status === "ok" ? (
                <p className="mt-1 text-xs text-ink-faint">
                  同期完了{syncMut.data.recomputed_days ? `(${syncMut.data.recomputed_days}日分)` : ""}
                </p>
              ) : (
                <p className="mt-1 text-xs text-risk">{syncErrorMessage(syncMut.data.reason)}</p>
              )
            )}
          </div>
        </>
      )}
    </div>
  );
}
