import { useCallback, useEffect, useRef, useState } from "react";
import { bpmToInterval } from "../lib/measure";

/**
 * Web Audio API のメトロノーム。lookahead スケジューラ (25ms ごとに先読みし、
 * AudioContext の currentTime 基準で次拍をスケジュール) で setInterval 揺れの影響を抑える。
 * iOS Safari 対策で start() はユーザー操作起点に AudioContext を生成/resume する。
 */
export function useMetronome(bpm: number) {
  const ctxRef = useRef<AudioContext | null>(null);
  const timerRef = useRef<number | null>(null);
  const nextNoteRef = useRef(0); // 次の拍をスケジュールする時刻 (ctx.currentTime 基準, 秒)
  const [isRunning, setIsRunning] = useState(false);
  const [beat, setBeat] = useState(0);

  const interval = bpmToInterval(bpm);

  /** 単発のクリック音 (短いオシレータビープ) を指定時刻にスケジュール。 */
  const click = useCallback((ctx: AudioContext, time: number, freq = 1000) => {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(0.0001, time);
    gain.gain.exponentialRampToValueAtTime(0.4, time + 0.005);
    gain.gain.exponentialRampToValueAtTime(0.0001, time + 0.05);
    osc.connect(gain).connect(ctx.destination);
    osc.start(time);
    osc.stop(time + 0.06);
  }, []);

  const stop = useCallback(() => {
    if (timerRef.current != null) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    setIsRunning(false);
  }, []);

  const start = useCallback(async () => {
    if (isRunning) return;
    const Ctx = window.AudioContext || (window as any).webkitAudioContext;
    if (!ctxRef.current) ctxRef.current = new Ctx();
    const ctx = ctxRef.current;
    await ctx.resume();
    setBeat(0);
    nextNoteRef.current = ctx.currentTime + 0.1;
    setIsRunning(true);
    timerRef.current = window.setInterval(() => {
      // 100ms 先までの拍をスケジュール。
      while (nextNoteRef.current < ctx.currentTime + 0.1) {
        click(ctx, nextNoteRef.current);
        nextNoteRef.current += interval;
        setBeat((b) => b + 1);
      }
    }, 25);
  }, [isRunning, interval, click]);

  /** 開始/終了の合図など、即時に1発鳴らす。 */
  const beep = useCallback(
    async (freq = 1400) => {
      const Ctx = window.AudioContext || (window as any).webkitAudioContext;
      if (!ctxRef.current) ctxRef.current = new Ctx();
      const ctx = ctxRef.current;
      await ctx.resume();
      click(ctx, ctx.currentTime + 0.02, freq);
    },
    [click],
  );

  useEffect(
    () => () => {
      if (timerRef.current != null) clearInterval(timerRef.current);
      ctxRef.current?.close().catch(() => {});
    },
    [],
  );

  return { start, stop, beep, isRunning, beat };
}
