import { useEffect, useState } from "react";
import { TodayPage } from "./pages/Today";
import { DebugPage } from "./pages/Debug";

type View = "today" | "debug";

function viewFromHash(): View {
  return window.location.hash === "#debug" ? "debug" : "today";
}

export default function App() {
  const [view, setView] = useState<View>(viewFromHash);

  useEffect(() => {
    const handler = () => setView(viewFromHash());
    window.addEventListener("hashchange", handler);
    return () => window.removeEventListener("hashchange", handler);
  }, []);

  return (
    <>
      {/* スクロール時にコンテンツが iOS ステータスバーの文字と重ならないよう、
          safe-area 上端を背景色で覆う固定スクリム */}
      <div aria-hidden className="status-bar-scrim" />
      {view === "debug" ? (
        <DebugPage
          onBack={() => {
            window.location.hash = "";
          }}
        />
      ) : (
        <TodayPage onOpenDebug={() => (window.location.hash = "#debug")} />
      )}
    </>
  );
}
