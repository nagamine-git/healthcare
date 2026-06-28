import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { kindLabel } from "../lib/labels";

type Phase = "idle" | "running" | "done";

/**
 * 着火タイマー: 「まず◯分だけ」で開始の心理的ハードルを下げる(2分ルール/行動活性化)。
 * 本質は時間ではなく "やめてもいい下限" を置くこと → 始めれば慣性で続く。
 * 完了すると対応する行動カテゴリ(kind)を庭に記録できる。
 */
export function IgnitionTimer({
  minutes,
  kind,
}: {
  minutes?: number | null;
  kind?: string | null;
}) {
  const qc = useQueryClient();
  const m = Math.max(1, Math.min(60, Math.round(minutes || 5)));
  const [phase, setPhase] = useState<Phase>("idle");
  const [left, setLeft] = useState(m * 60);
  const timer = useRef<number | null>(null);

  const log = useMutation({
    mutationFn: (k: string) => api.gardenLog(k),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["garden"] });
      qc.invalidateQueries({ queryKey: ["becoming"] });
      qc.invalidateQueries({ queryKey: ["today"] });
      qc.invalidateQueries({ queryKey: ["life-tree"] });
    },
  });

  useEffect(() => {
    if (phase !== "running") return;
    timer.current = window.setInterval(() => {
      setLeft((s) => {
        if (s <= 1) {
          if (timer.current) window.clearInterval(timer.current);
          setPhase("done");
          return 0;
        }
        return s - 1;
      });
    }, 1000);
    return () => {
      if (timer.current) window.clearInterval(timer.current);
    };
  }, [phase]);

  const start = () => {
    setLeft(m * 60);
    setPhase("running");
  };
  const stop = () => {
    if (timer.current) window.clearInterval(timer.current);
    setPhase("idle");
    setLeft(m * 60);
  };
  const mmss = `${String(Math.floor(left / 60)).padStart(2, "0")}:${String(left % 60).padStart(2, "0")}`;

  if (phase === "idle") {
    return (
      <button
        onClick={start}
        className="rounded-lg bg-act/15 px-3 py-1.5 text-sm font-medium text-act-300 ring-1 ring-act-700/40 transition-colors hover:bg-act/25"
      >
        ▶ まず{m}分はじめる
      </button>
    );
  }
  if (phase === "running") {
    return (
      <div className="flex items-center gap-3">
        <span className="telemetry-num text-2xl font-bold text-act-300">{mmss}</span>
        <span className="text-xs text-ink-faint">手を動かすだけ。やめても“着火”は成功。</span>
        <button onClick={stop} className="ml-auto text-xs text-ink-faint hover:text-ink-dim">
          やめる
        </button>
      </div>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-sm font-medium text-prog-300">✓ {m}分 着火できた</span>
      <button
        onClick={start}
        className="rounded-lg border border-hairline px-2.5 py-1 text-xs text-ink-dim transition-colors hover:text-ink"
      >
        続ける(+{m}分)
      </button>
      {kind && (
        <button
          disabled={log.isPending || log.isSuccess}
          onClick={() => log.mutate(kind)}
          className="rounded-lg bg-prog-700 px-2.5 py-1 text-xs font-medium text-ink transition-colors hover:bg-prog-500 disabled:opacity-50"
        >
          {log.isSuccess ? "✓ 記録済み" : `${kindLabel(kind)}を記録`}
        </button>
      )}
    </div>
  );
}
