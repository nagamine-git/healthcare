import { useCallback, useEffect, useState } from "react";
import { Bell, BellOff, Smartphone } from "lucide-react";
import {
  disablePush,
  enablePush,
  getPushState,
  isStandalone,
  pushSupported,
  sendTestPush,
  type PushState,
} from "../lib/push";

/**
 * Web Push 通知の ON/OFF と動作確認。
 *
 * 鳴らす対象は「明らかにやるべき / 明らかに危険」に限定 (サーバ側 engine):
 *   - critical アラート (慢性睡眠不足・低体重・MOH 等) を毎朝まとめて 1 回
 *   - time_jst を持つ high/critical アクション (カフェイン遮断・ナップ等) をその時刻に
 *   - 就寝リマインド (任意)
 */
export function NotificationSettings() {
  const [state, setState] = useState<PushState | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setState(await getPushState());
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const onEnable = async () => {
    setBusy(true);
    setMsg(null);
    const r = await enablePush();
    if (r.ok) {
      setMsg("通知をオンにしました。");
    } else {
      const reasons: Record<string, string> = {
        unsupported: "このブラウザは Web Push に未対応です。",
        not_standalone:
          "iPhone では、共有メニューから「ホーム画面に追加」して、追加したアプリから開くと有効化できます。",
        server_disabled: "サーバ側で通知が無効です (VAPID 鍵未設定)。",
        denied: "通知が許可されませんでした。ブラウザ設定から許可してください。",
        error: `エラー: ${r.detail ?? ""}`,
      };
      setMsg(reasons[r.reason] ?? "有効化に失敗しました。");
    }
    await refresh();
    setBusy(false);
  };

  const onDisable = async () => {
    setBusy(true);
    setMsg(null);
    await disablePush();
    setMsg("通知をオフにしました。");
    await refresh();
    setBusy(false);
  };

  const onTest = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const sent = await sendTestPush();
      setMsg(sent > 0 ? "テスト通知を送信しました。" : "送信先がありません。先にオンにしてください。");
    } catch (e) {
      setMsg(`送信に失敗しました: ${String(e)}`);
    }
    setBusy(false);
  };

  const supported = pushSupported();
  const iOS = /iP(hone|ad|od)/.test(navigator.userAgent);
  const needsInstall = iOS && !isStandalone();

  return (
    <div className="rounded-2xl bg-slate-900/40 p-4">
      <div className="mb-2 flex items-center gap-2">
        <Bell size={15} className="text-amber-300" />
        <h3 className="text-sm font-semibold text-slate-200">通知</h3>
      </div>
      <p className="mb-3 text-[11px] leading-relaxed text-slate-500">
        危険アラートと、時間が決まっている重要アクション (カフェイン遮断・ナップ・就寝準備など) だけを
        その時刻に通知します。それ以外は通知しません。
      </p>

      {!supported && (
        <p className="text-xs text-rose-300">このブラウザは Web Push に未対応です。</p>
      )}

      {supported && needsInstall && (
        <div className="mb-3 flex items-start gap-2 rounded-xl bg-amber-500/10 p-3 text-[11px] text-amber-200">
          <Smartphone size={14} className="mt-0.5 shrink-0" />
          <span>
            iPhone では通知を使うのに PWA インストールが必要です。共有メニュー →「ホーム画面に追加」で
            追加し、そのアイコンから開いてからオンにしてください。
          </span>
        </div>
      )}

      {supported && (
        <div className="flex flex-wrap items-center gap-2">
          {state?.subscribed ? (
            <button
              onClick={onDisable}
              disabled={busy}
              className="inline-flex items-center gap-1.5 rounded-lg bg-slate-700/60 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-700 disabled:opacity-50"
            >
              <BellOff size={13} /> 通知をオフ
            </button>
          ) : (
            <button
              onClick={onEnable}
              disabled={busy || needsInstall}
              className="inline-flex items-center gap-1.5 rounded-lg bg-amber-500/80 px-3 py-1.5 text-xs font-medium text-slate-900 hover:bg-amber-400 disabled:opacity-50"
            >
              <Bell size={13} /> 通知をオン
            </button>
          )}
          <button
            onClick={onTest}
            disabled={busy || !state?.subscribed}
            className="inline-flex items-center gap-1.5 rounded-lg bg-slate-800/60 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800 disabled:opacity-40"
          >
            テスト送信
          </button>
          <span className="text-[11px] text-slate-500">
            {state?.subscribed ? "オン" : "オフ"}
            {state && !state.serverEnabled ? " / サーバ未設定" : ""}
          </span>
        </div>
      )}

      {msg && <p className="mt-2 text-[11px] text-slate-400">{msg}</p>}
    </div>
  );
}
