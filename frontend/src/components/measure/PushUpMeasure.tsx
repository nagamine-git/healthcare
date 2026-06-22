import { useEffect, useRef, useState } from "react";
import { useMetronome } from "../../hooks/useMetronome";
import { bpmToInterval, repIntervalSec, shouldAutoStop } from "../../lib/measure";

const BPM = 80;

/**
 * 腕立て (80bpm) の測定。3-2-1 リードイン後にメトロノーム開始。特大ボタンを顎でタッチ=1回。
 * 最後のタップから「1回分+3拍」遅れたら自動停止 (プロトコル「3拍以上遅れたら終了」)。
 */
export function PushUpMeasure({ onFinish }: { onFinish: (count: number) => void }) {
  const metro = useMetronome(BPM);
  const [lead, setLead] = useState(3); // 3-2-1 リードイン
  const [counting, setCounting] = useState(false);
  const [count, setCount] = useState(0);
  const lastTapRef = useRef<number | null>(null);

  // 3-2-1 → メトロノーム開始
  useEffect(() => {
    if (lead <= 0) return;
    const id = setTimeout(() => setLead((n) => n - 1), 1000);
    return () => clearTimeout(id);
  }, [lead]);

  useEffect(() => {
    if (lead === 0 && !counting) {
      setCounting(true);
      void metro.start();
    }
  }, [lead, counting, metro]);

  // 自動停止監視 (最初のタップ後のみ)
  useEffect(() => {
    if (!counting) return;
    const id = setInterval(() => {
      if (lastTapRef.current == null) return;
      if (shouldAutoStop(lastTapRef.current, performance.now(), repIntervalSec(BPM), bpmToInterval(BPM))) {
        metro.stop();
        onFinish(count);
      }
    }, 200);
    return () => clearInterval(id);
  }, [counting, count, metro, onFinish]);

  const tap = () => {
    lastTapRef.current = performance.now();
    setCount((c) => c + 1);
  };

  const finish = () => {
    metro.stop();
    onFinish(count);
  };

  if (lead > 0) {
    return (
      <div className="text-center">
        <div className="text-sm text-slate-400">まもなく開始</div>
        <div className="mt-2 text-7xl font-bold tabular-nums text-sky-300">{lead}</div>
        <div className="mt-4 text-xs text-slate-500">80bpm・下げ1拍/上げ1拍。胸が床から握りこぶし1個分まで。</div>
      </div>
    );
  }

  return (
    <div className="flex w-full max-w-sm flex-1 flex-col items-center justify-between py-4">
      <div className="text-center">
        <div className="text-xs text-slate-400">回数</div>
        <div className="text-8xl font-bold tabular-nums text-slate-100">{count}</div>
        <div className="mt-1 text-[11px] text-amber-300/70">押し上げで息を吐く (息こらえ回避)</div>
      </div>
      <button
        type="button"
        onPointerDown={tap}
        className="my-6 flex aspect-square w-full select-none items-center justify-center rounded-3xl bg-sky-600/90 text-2xl font-bold text-white ring-4 ring-sky-400/30 active:bg-sky-500"
      >
        顎でタッチ
      </button>
      <button
        type="button"
        onClick={finish}
        className="w-full rounded-xl bg-slate-800 py-3 text-sm font-medium text-slate-200 hover:bg-slate-700"
      >
        終了して記録へ
      </button>
    </div>
  );
}
