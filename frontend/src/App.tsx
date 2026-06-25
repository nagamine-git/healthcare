import { useEffect, useState } from "react";
import { TodayPage } from "./pages/Today";
import { DebugPage } from "./pages/Debug";
import { IdentityPage } from "./pages/Identity";
import { GardenPage } from "./pages/Garden";
import { BecomingPage } from "./pages/Becoming";
import { CommandCenter } from "./pages/CommandCenter";
import { BottomNav } from "./components/ui/BottomNav";

type View = "home" | "today" | "debug" | "identity" | "garden" | "becoming";

function viewFromHash(): View {
  if (window.location.hash === "#debug") return "debug";
  if (window.location.hash === "#identity") return "identity";
  if (window.location.hash === "#garden") return "garden";
  if (window.location.hash === "#becoming") return "becoming";
  if (window.location.hash === "#today") return "today";
  return "home";
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
      ) : view === "identity" ? (
        <IdentityPage
          onBack={() => {
            window.location.hash = "";
          }}
        />
      ) : view === "garden" ? (
        <GardenPage
          onBack={() => {
            window.location.hash = "";
          }}
        />
      ) : view === "becoming" ? (
        <BecomingPage
          onBack={() => {
            window.location.hash = "";
          }}
        />
      ) : view === "today" ? (
        <TodayPage onOpenDebug={() => (window.location.hash = "#debug")} />
      ) : (
        <CommandCenter onOpenSettings={() => (window.location.hash = "#today")} />
      )}
      {/* 全画面に常設のナビ(コンテンツが隠れないよう各ページ末尾に余白を確保) */}
      <div className="h-16" aria-hidden />
      <BottomNav current={view} />
    </>
  );
}
