import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { LifeTreePanel } from "../components/LifeTreePanel";
import { LifePortfolioPanel } from "../components/LifePortfolioPanel";
import { Button, Panel } from "../components/ui/cockpit";

function GoalEditor() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["life-tree"], queryFn: api.lifeTree });
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [horizon, setHorizon] = useState("");
  const [weights, setWeights] = useState<Record<string, number>>({});

  const start = () => {
    const g = q.data?.goal;
    setTitle(g?.title ?? "");
    setHorizon(g?.horizon ?? "");
    const w: Record<string, number> = {};
    for (const c of q.data?.capitals ?? []) w[c.key] = c.weight;
    setWeights(w);
    setOpen(true);
  };

  const save = useMutation({
    mutationFn: () => api.lifeGoal({ title, horizon, capital_weights: weights }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["life-tree"] });
      setOpen(false);
    },
  });

  if (!q.data) return null;

  return (
    <Panel
      title="目標を編集"
      action={
        !open ? (
          <Button variant="ghost" onClick={start}>
            編集
          </Button>
        ) : undefined
      }
    >
      {!open ? (
        <p className="text-sm text-ink-dim">
          {q.data.goal?.title ?? "未設定"}
          {q.data.goal?.horizon ? `(${q.data.goal.horizon})` : ""}
        </p>
      ) : (
        <div className="space-y-2">
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="目標(例: AI活用でユニコーンを立ち上げる)"
            className="w-full rounded bg-panel px-2 py-1 text-sm text-ink"
          />
          <input
            value={horizon}
            onChange={(e) => setHorizon(e.target.value)}
            placeholder="期限(例: 2年)"
            className="w-full rounded bg-panel px-2 py-1 text-sm text-ink"
          />
          <p className="telemetry-label pt-1">重点ウェイト(大きいほど力を入れる)</p>
          <div className="space-y-1">
            {q.data.capitals.map((c) => (
              <label key={c.key} className="flex items-center gap-2 text-sm text-ink-dim">
                <span className="w-24">{c.label}</span>
                <input
                  type="number"
                  step="0.5"
                  min="0"
                  value={weights[c.key] ?? 1}
                  onChange={(e) =>
                    setWeights((w) => ({ ...w, [c.key]: parseFloat(e.target.value) || 0 }))
                  }
                  className="w-16 rounded bg-panel px-2 py-0.5 text-sm text-ink"
                />
              </label>
            ))}
          </div>
          <div className="flex gap-2 pt-1">
            <Button variant="primary" disabled={save.isPending || !title} onClick={() => save.mutate()}>
              {save.isPending ? "保存中…" : "保存"}
            </Button>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              キャンセル
            </Button>
          </div>
        </div>
      )}
    </Panel>
  );
}

export function LifePage({ onBack }: { onBack: () => void }) {
  return (
    <div className="safe-area-top safe-area-x pb-nav mx-auto max-w-3xl space-y-4">
      <button onClick={onBack} className="telemetry-label hover:text-ink">
        ← 戻る
      </button>
      <h1 className="text-xl font-bold text-ink">人生 — 最適化ツリー</h1>
      <p className="text-xs text-ink-faint">
        目的 → 目標 → ドメイン → 行動。重点に寄せつつ、最低ラインは守る。
      </p>
      <LifePortfolioPanel />
      <LifeTreePanel />
      <GoalEditor />
      <button
        onClick={() => (window.location.hash = "#checkup")}
        className="w-full rounded-xl border border-hairline bg-hull p-3 text-left text-sm text-ink-dim transition-colors hover:border-ink-faint"
      >
        🩺 健康診断の結果を取り込む(身体資本の判断材料)→
      </button>
    </div>
  );
}
