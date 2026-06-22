import { useCallback, useEffect, useRef, useState } from "react";
import { isOnset } from "../lib/measure";

const THRESHOLD = 0.12; // RMS の立ち上がり閾値 (環境ノイズで要調整)
const REFRACTORY_MS = 400; // 1音1カウントにするための不応期

/**
 * マイク入力の音量オンセット (声/物音/足音/手拍子) をカウントする。
 * getUserMedia → AnalyserNode の RMS を rAF で監視し、閾値を跨いだ瞬間+不応期で +1。
 * 権限拒否/非対応では denied/supported=false を立て、呼び出し側で手入力へフォールバック。
 * 誤検出があるので adjust/reset で手動補正できる。
 */
export function useOnsetCounter() {
  const [count, setCount] = useState(0);
  const [denied, setDenied] = useState(false);
  const supported =
    typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia;

  const streamRef = useRef<MediaStream | null>(null);
  const ctxRef = useRef<AudioContext | null>(null);
  const rafRef = useRef<number | null>(null);

  const stop = useCallback(() => {
    if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    rafRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    ctxRef.current?.close().catch(() => {});
    ctxRef.current = null;
  }, []);

  const start = useCallback(async () => {
    if (!supported) {
      setDenied(true);
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const Ctx = window.AudioContext || (window as any).webkitAudioContext;
      const ctx = new Ctx();
      ctxRef.current = ctx;
      const source = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 1024;
      source.connect(analyser);
      const buf = new Float32Array(analyser.fftSize);
      let prev = 0;
      let lastCountAt = 0;
      const tick = (t: number) => {
        analyser.getFloatTimeDomainData(buf);
        let sum = 0;
        for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
        const rms = Math.sqrt(sum / buf.length);
        if (isOnset(rms, prev, THRESHOLD) && t - lastCountAt > REFRACTORY_MS) {
          lastCountAt = t;
          setCount((c) => c + 1);
        }
        prev = rms;
        rafRef.current = requestAnimationFrame(tick);
      };
      rafRef.current = requestAnimationFrame(tick);
    } catch {
      setDenied(true);
      stop();
    }
  }, [supported, stop]);

  const adjust = useCallback((d: number) => setCount((c) => Math.max(0, c + d)), []);
  const reset = useCallback(() => setCount(0), []);

  useEffect(() => stop, [stop]);

  return { count, start, stop, adjust, reset, supported, denied };
}
