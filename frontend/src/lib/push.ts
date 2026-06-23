/* ブラウザ側の Web Push 購読フロー。
 *
 * iOS の制約: 通知はホーム画面に「追加」した PWA (standalone 表示) かつ
 * iOS 16.4 以降でのみ動作する。Safari のタブでは Notification.requestPermission が
 * 失敗するため、standalone でない場合はインストール導線を案内する。
 */

import { api } from "./api";

export type PushState = {
  supported: boolean;
  standalone: boolean;
  permission: NotificationPermission | "unsupported";
  subscribed: boolean;
  serverEnabled: boolean;
};

export function isStandalone(): boolean {
  // iOS Safari は navigator.standalone、その他は display-mode: standalone
  const iosStandalone = (window.navigator as unknown as { standalone?: boolean }).standalone;
  return (
    iosStandalone === true ||
    window.matchMedia?.("(display-mode: standalone)").matches === true
  );
}

export function pushSupported(): boolean {
  return (
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window
  );
}

function urlBase64ToUint8Array(base64String: string): Uint8Array<ArrayBuffer> {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  const buf = new ArrayBuffer(raw.length);
  const arr = new Uint8Array(buf);
  for (let i = 0; i < raw.length; i += 1) arr[i] = raw.charCodeAt(i);
  return arr;
}

async function existingSubscription(): Promise<PushSubscription | null> {
  if (!pushSupported()) return null;
  try {
    const reg = await navigator.serviceWorker.ready;
    return await reg.pushManager.getSubscription();
  } catch {
    return null;
  }
}

export async function getPushState(): Promise<PushState> {
  const supported = pushSupported();
  let serverEnabled = false;
  try {
    serverEnabled = (await api.pushConfig()).enabled;
  } catch {
    serverEnabled = false;
  }
  const sub = await existingSubscription();
  return {
    supported,
    standalone: isStandalone(),
    permission: supported ? Notification.permission : "unsupported",
    subscribed: sub !== null,
    serverEnabled,
  };
}

export type EnableResult =
  | { ok: true }
  | { ok: false; reason: "unsupported" | "not_standalone" | "server_disabled" | "denied" | "error"; detail?: string };

export async function enablePush(): Promise<EnableResult> {
  if (!pushSupported()) return { ok: false, reason: "unsupported" };
  // iOS はホーム画面 PWA でのみ許可ダイアログが出せる
  const iOS = /iP(hone|ad|od)/.test(navigator.userAgent);
  if (iOS && !isStandalone()) return { ok: false, reason: "not_standalone" };

  let cfg;
  try {
    cfg = await api.pushConfig();
  } catch (e) {
    return { ok: false, reason: "error", detail: String(e) };
  }
  if (!cfg.enabled || !cfg.vapid_public_key) return { ok: false, reason: "server_disabled" };

  const perm = await Notification.requestPermission();
  if (perm !== "granted") return { ok: false, reason: "denied" };

  try {
    const reg = await navigator.serviceWorker.ready;
    let sub = await reg.pushManager.getSubscription();
    if (!sub) {
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(cfg.vapid_public_key),
      });
    }
    await api.pushSubscribe(sub.toJSON());
    return { ok: true };
  } catch (e) {
    return { ok: false, reason: "error", detail: String(e) };
  }
}

export async function disablePush(): Promise<void> {
  const sub = await existingSubscription();
  if (!sub) return;
  try {
    await api.pushUnsubscribe(sub.endpoint);
  } catch {
    /* サーバ側が既に消えていても続行 */
  }
  try {
    await sub.unsubscribe();
  } catch {
    /* 無視 */
  }
}

export async function sendTestPush(): Promise<number> {
  const r = await api.pushTest();
  return r.sent;
}
