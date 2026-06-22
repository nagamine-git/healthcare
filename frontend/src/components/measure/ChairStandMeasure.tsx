import { useEffect, useRef, useState } from "react";
import { Minus, Plus } from "lucide-react";
import { useMetronome } from "../../hooks/useMetronome";
import { useOnsetCounter } from "../../hooks/useOnsetCounter";

const DURATION = 30; // 秒

/**
 * 30秒椅子立ち上がりの測定。開始/終了ビープ + 30秒カウントダウン。
 * マイクのオンセット (声/物音/足音) を立ち座りのカウント代理にする。±で手動補正。
 * マイク拒否/非対応ならタイマーのみ + 手動カウント (+/-) にフォールバック。
 */
export function ChairStandMeasure({ onFinish }: { onFinish: (count: number) => void }) {
  const { beep } = useMetronome(60);
  const onset = useOnsetCounter();
  const [lead, setLead] = useState(3);
  const [remaining, setRemaining] = useState(DURATION);
  const [running, setRunning] = useState(false);
  const finishedRef = useRef(false);

  // 3-2-1 リードイン
  useEffect(() => {
    if (lead <= 0) return;
    const id = setTimeout(() => setLead((n) => n - 1), 1000);
    return () => clearTimeout(id);
  }, [lead]);

  // 開始: ビープ + マイク + カウントダウン
  useEffect(() => {
    if (lead !== 0 || running) return;
    setRunning(true);
    void beep(1600);
    void onset.start();
  }, [lead, running, beep, onset]);

  useEffect(() => {
    if (!running || remaining <= 0) return;
    const id = setTimeout(() => setRemaining((s) => s - 1), 1000);
    return () => clearTimeout(id);
  }, [running, remaining]);

  // 終了
  useEffect(() => {
    if (!running || remaining > 0 || finishedRef.current) return;
    finishedRef.current = true;
    void beep(1600);
    onset.stop();
    const id = setTimeout(() => onFinish(onset.count), 300);
    return () => clearTimeout(id);
  }, [running, remaining, beep, onset, onFinish]);

  if (lead > 0) {
    return (
      <div className="text-center">
        <div className="text-sm text-slate-400">まもなく開始</div>
        <div className="mt-2 text-7xl font-bold tabular-nums text-sky-300">{lead}</div>
        <div className="mt-4 text-xs text-slate-500">腕を胸の前で組み、30秒で完全な立ち座りを繰り返す。</div>
      </div>
    );
  }

  return (
    <div className="flex w-full max-w-sm flex-col items-center gap-6">
      <div className="text-center">
        <div className="text-xs text-slate-400">残り</div>
        <div className="text-6xl font-bold tabular-nums text-sky-300">{remaining}s</div>
      </div>
      <div className="text-center">
        <div className="text-xs text-slate-400">回数</div>
        <div className="text-8xl font-bold tabular-nums text-slate-100">{onset.count}</div>
        <div className="mt-1 text-[11px] text-amber-300/70">立ち上がりで息を吐く</div>
      </div>
      {onset.denied && (
        <div className="rounded-lg bg-slate-900/60 px-3 py-2 text-center text-[11px] text-amber-300/80">
          マイクが使えないので、+ ボタンで自分で数えてください
        </div>
      )}
      <div className="flex items-center gap-4">
        <button
          type="button"
          onClick={() => onset.adjust(-1)}
          className="flex h-14 w-14 items-center justify-center rounded-full bg-slate-800 text-slate-200 hover:bg-slate-700"
        >
          <Minus size={22} />
        </button>
        <button
          type="button"
          onClick={() => onset.adjust(1)}
          className="flex h-16 w-16 items-center justify-center rounded-full bg-sky-600/90 text-white ring-4 ring-sky-400/30 active:bg-sky-500"
        >
          <Plus size={26} />
        </button>
      </div>
      <button
        type="button"
        onClick={() => {
          onset.stop();
          onFinish(onset.count);
        }}
        className="w-full rounded-xl bg-slate-800 py-3 text-sm font-medium text-slate-200 hover:bg-slate-700"
      >
        終了して記録へ
      </button>
    </div>
  );
}
