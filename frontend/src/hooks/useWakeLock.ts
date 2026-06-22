import { useCallback, useEffect, useRef } from "react";

/**
 * 画面スリープ防止 (Screen Wake Lock API)。測定中だけ取得し、終了/アンマウントで解放。
 * 非対応ブラウザでは無害な no-op。タブ復帰時に失われたロックを再取得する。
 */
export function useWakeLock() {
  const sentinelRef = useRef<WakeLockSentinel | null>(null);
  const wantRef = useRef(false);

  const request = useCallback(async () => {
    wantRef.current = true;
    try {
      if ("wakeLock" in navigator) {
        sentinelRef.current = await navigator.wakeLock.request("screen");
      }
    } catch {
      // 取得失敗 (権限/可視性) は無視して機能継続。
    }
  }, []);

  const release = useCallback(() => {
    wantRef.current = false;
    sentinelRef.current?.release().catch(() => {});
    sentinelRef.current = null;
  }, []);

  useEffect(() => {
    const onVisible = () => {
      if (wantRef.current && document.visibilityState === "visible") void request();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      release();
    };
  }, [request, release]);

  return { request, release };
}
