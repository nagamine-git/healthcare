import { useEffect, useState } from "react";
import { TodayPage } from "./pages/Today";
import { DebugPage } from "./pages/Debug";
import { IdentityPage } from "./pages/Identity";
import { GardenPage } from "./pages/Garden";
import { BecomingPage } from "./pages/Becoming";
import { LifePage } from "./pages/Life";
import { CheckupPage } from "./pages/Checkup";
import { JournalPage } from "./pages/Journal";
import { BottomNav } from "./components/ui/BottomNav";

type View = "home" | "debug" | "identity" | "garden" | "becoming" | "life" | "checkup" | "journal";

function viewFromHash(): View {
  if (window.location.hash === "#debug") return "debug";
  if (window.location.hash === "#identity") return "identity";
  if (window.location.hash === "#garden") return "garden";
  if (window.location.hash === "#becoming") return "becoming";
  if (window.location.hash === "#life") return "life";
  if (window.location.hash === "#checkup") return "checkup";
  if (window.location.hash === "#journal") return "journal";
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
        <DebugPage onBack={() => (window.location.hash = "")} />
      ) : view === "identity" ? (
        <IdentityPage onBack={() => (window.location.hash = "")} />
      ) : view === "garden" ? (
        <GardenPage onBack={() => (window.location.hash = "")} />
      ) : view === "becoming" ? (
        <BecomingPage onBack={() => (window.location.hash = "")} />
      ) : view === "life" ? (
        <LifePage onBack={() => (window.location.hash = "")} />
      ) : view === "checkup" ? (
        <CheckupPage onBack={() => (window.location.hash = "")} />
      ) : view === "journal" ? (
        <JournalPage onBack={() => (window.location.hash = "")} />
      ) : (
        <TodayPage onOpenDebug={() => (window.location.hash = "#debug")} />
      )}
      {/* 全画面に常設のナビ(各ページが .pb-nav で下余白を確保) */}
      <BottomNav current={view} />
    </>
  );
}
