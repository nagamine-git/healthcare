import { useEffect } from "react";
import { useWakeLock } from "../../hooks/useWakeLock";
import { setAudioSession } from "../../lib/audioSession";
import { PushUpMeasure } from "./PushUpMeasure";
import { ChairStandMeasure } from "./ChairStandMeasure";

export type MeasureMode = "metronome_tap" | "timer_clap";

/**
 * 全画面「測定モード」シェル。Wake Lock をここで取得/解放し、mode で測定本体を出し分ける。
 * onFinish(count) で確定回数を親 (TestCard) の入力欄へ戻す (自動送信はしない)。
 */
export function MeasureModal({
  mode,
  label,
  onFinish,
  onClose,
}: {
  mode: MeasureMode;
  label: string;
  onFinish: (count: number) => void;
  onClose: () => void;
}) {
  const wake = useWakeLock();
  useEffect(() => {
    void wake.request();
    // サイレントモードでも鳴らす。マイクを使う椅子は play-and-record。
    setAudioSession(mode === "timer_clap" ? "play-and-record" : "playback");
    return () => {
      wake.release();
      setAudioSession("auto");
    };
  }, [wake, mode]);

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-slate-950/95 backdrop-blur-sm">
      <div className="flex items-center justify-between px-4 py-3">
        <span className="text-sm text-slate-300">{label}</span>
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg px-3 py-1.5 text-xs text-slate-400 hover:bg-slate-800 hover:text-slate-200"
        >
          中止
        </button>
      </div>
      <div className="flex flex-1 flex-col items-center justify-center px-6 pb-10">
        {mode === "metronome_tap" ? (
          <PushUpMeasure onFinish={onFinish} />
        ) : (
          <ChairStandMeasure onFinish={onFinish} />
        )}
      </div>
    </div>
  );
}
