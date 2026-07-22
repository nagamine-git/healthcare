import { useEffect } from "react";

/// ネイティブシェル (Ascend WKWebView) のスリープ禁止ブリッジがあるか。
interface KeepAwakeBridge {
  postMessage: (on: boolean) => void;
}
function nativeBridge(): KeepAwakeBridge | null {
  const w = window as unknown as {
    webkit?: { messageHandlers?: { keepAwake?: KeepAwakeBridge } };
  };
  return w.webkit?.messageHandlers?.keepAwake ?? null;
}

/// 画面を消させない (auto-lock 抑止)。呼吸セッション/トレ実行中に使う。
///
/// 経路は 2 つ: ①ネイティブシェル (Ascend) の keepAwake ブリッジ (WKWebView は
/// Web Wake Lock API を持たないのでこちらが本命)。②ブラウザ直開き時は
/// navigator.wakeLock にフォールバック。`active` が true の間だけ有効。
export function useWakeLock(active: boolean): void {
  useEffect(() => {
    if (!active) return;

    const native = nativeBridge();
    if (native) {
      native.postMessage(true);
      return () => native.postMessage(false);
    }

    // フォールバック: Web Screen Wake Lock (Safari 16.4+/対応ブラウザ)。
    let sentinel: { release: () => Promise<void> } | null = null;
    let released = false;
    const nav = navigator as Navigator & {
      wakeLock?: { request: (type: "screen") => Promise<{ release: () => Promise<void> }> };
    };
    nav.wakeLock
      ?.request("screen")
      .then((s) => {
        if (released) void s.release();
        else sentinel = s;
      })
      .catch(() => {
        /* 取得できなくても機能自体は続行 */
      });

    // タブ復帰時に取り直す (wake lock は不可視化で自動解放される)。
    const onVisible = () => {
      if (document.visibilityState === "visible" && !released) {
        nav.wakeLock
          ?.request("screen")
          .then((s) => {
            sentinel = s;
          })
          .catch(() => {});
      }
    };
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      released = true;
      document.removeEventListener("visibilitychange", onVisible);
      void sentinel?.release();
    };
  }, [active]);
}
