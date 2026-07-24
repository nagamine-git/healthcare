/// 呼吸セッションの音・触覚フィードバック。
///
/// 音: Web Audio の柔らかいトーン。iOS の WKWebView / Safari では Web Audio は
/// **端末のサイレントスイッチを尊重**するので、サイレント時は自然に鳴らない
/// (要件「サイレントのときは音鳴らさない」を追加処理なしで満たす)。
/// 触覚: ネイティブ (Ascend) の haptic ブリッジ優先、なければ navigator.vibrate。

let audioCtx: AudioContext | null = null;

function ctx(): AudioContext | null {
  if (typeof window === "undefined") return null;
  if (audioCtx) return audioCtx;
  const AC =
    (window as unknown as { AudioContext?: typeof AudioContext; webkitAudioContext?: typeof AudioContext })
      .AudioContext ??
    (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!AC) return null;
  try {
    audioCtx = new AC();
  } catch {
    return null;
  }
  return audioCtx;
}

/// ユーザー操作 (開始ボタン) の中で一度呼んで AudioContext を起こす。
export function primeAudio(): void {
  const c = ctx();
  if (c && c.state === "suspended") void c.resume();
}

/// 柔らかいトーンを鳴らす。freq=周波数(Hz), durMs=長さ。サイレント時は無音。
export function tone(freq: number, durMs = 320): void {
  const c = ctx();
  if (!c) return;
  if (c.state === "suspended") void c.resume();
  const osc = c.createOscillator();
  const gain = c.createGain();
  osc.type = "sine";
  osc.frequency.value = freq;
  // フェードイン/アウトで耳障りにならないように (クリックノイズ防止)。
  const now = c.currentTime;
  const dur = durMs / 1000;
  gain.gain.setValueAtTime(0, now);
  gain.gain.linearRampToValueAtTime(0.12, now + 0.04);
  gain.gain.linearRampToValueAtTime(0, now + dur);
  osc.connect(gain).connect(c.destination);
  osc.start(now);
  osc.stop(now + dur + 0.02);
}

interface HapticBridge {
  postMessage: (kind: string) => void;
}
function hapticBridge(): HapticBridge | null {
  const w = window as unknown as {
    webkit?: { messageHandlers?: { haptic?: HapticBridge } };
  };
  return w.webkit?.messageHandlers?.haptic ?? null;
}

/// 触覚フィードバック。kind = light|medium|heavy|soft|rigid。
export function haptic(kind: "light" | "medium" | "soft" = "light"): void {
  const bridge = hapticBridge();
  if (bridge) {
    bridge.postMessage(kind);
    return;
  }
  const nav = navigator as Navigator & { vibrate?: (p: number | number[]) => boolean };
  nav.vibrate?.(kind === "medium" ? 30 : 15);
}

interface HealthKitBridge {
  postMessage: (body: { type: "mindful"; minutes: number }) => void;
}
function healthKitBridge(): HealthKitBridge | null {
  const w = window as unknown as {
    webkit?: { messageHandlers?: { healthKit?: HealthKitBridge } };
  };
  return w.webkit?.messageHandlers?.healthKit ?? null;
}

/// 呼吸/瞑想の実施時間を Apple Health (マインドフルネス) に write-only で書き出す
/// (Phase2 / Ascend native の HealthKit ブリッジ向け先行仕込み)。
/// ネイティブブリッジが無い環境 (ブラウザ直開き等) では無害にスキップする。
/// 分析の真実源は自前DB (sleep_intervention_log) のまま — ここは書き出し専用。
export function writeMindful(minutes: number): void {
  const bridge = healthKitBridge();
  if (!bridge) return;
  bridge.postMessage({ type: "mindful", minutes });
}
