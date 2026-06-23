import { useEffect } from "react";
import { useIsMutating } from "@tanstack/react-query";

/**
 * 保存 (mutation) がまだ裏で飛んでいる間にタブ/アプリを閉じようとしたら警告する。
 *
 * 調子のドットなどは楽観更新 (即座に画面反映・通信は裏で) にしているため、
 * POST 完了前に閉じるとサーバへ届かず記録が失われうる。in-flight の mutation が
 * ある間だけ beforeunload を張って取りこぼしを防ぐ。
 */
export function UnsavedGuard() {
  const mutating = useIsMutating();
  useEffect(() => {
    if (!mutating) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = ""; // Chrome は returnValue 設定で確認ダイアログを出す
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [mutating]);
  return null;
}
