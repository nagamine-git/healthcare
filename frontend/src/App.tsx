import { useEffect, useState } from "react";
import { TodayPage } from "./pages/Today";
import { DebugPage } from "./pages/Debug";
import { CompassPage, type CompassSegment } from "./pages/Compass";
import { GardenPage } from "./pages/Garden";
import { CheckupPage } from "./pages/Checkup";
import { JournalPage } from "./pages/Journal";
import { FinancePage } from "./pages/Finance";
import { ConsultPage } from "./pages/Consult";
import { BottomNav } from "./components/ui/BottomNav";

type View = "home" | "debug" | "compass" | "garden" | "checkup" | "journal" | "finance" | "consult";

// 旧ハッシュ(#identity/#life/#becoming)は統合された羅針盤の各セグメントへ着地させる。
const COMPASS_HASHES: Record<string, CompassSegment> = {
  "#compass": "values",
  "#identity": "values",
  "#life": "purpose",
  "#becoming": "path",
};

function viewFromHash(): View {
  const h = window.location.hash;
  if (h === "#debug") return "debug";
  if (h in COMPASS_HASHES) return "compass";
  if (h === "#garden") return "garden";
  if (h === "#checkup") return "checkup";
  if (h === "#journal") return "journal";
  if (h === "#finance") return "finance";
  if (h === "#consult") return "consult";
  return "home";
}

export default function App() {
  const [view, setView] = useState<View>(viewFromHash);
  const [compassSeg, setCompassSeg] = useState<CompassSegment>(
    COMPASS_HASHES[window.location.hash] ?? "values",
  );

  useEffect(() => {
    const handler = () => {
      setView(viewFromHash());
      setCompassSeg(COMPASS_HASHES[window.location.hash] ?? "values");
    };
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
      ) : view === "compass" ? (
        <CompassPage initialSegment={compassSeg} />
      ) : view === "garden" ? (
        <GardenPage onBack={() => (window.location.hash = "")} />
      ) : view === "checkup" ? (
        <CheckupPage onBack={() => (window.location.hash = "")} />
      ) : view === "journal" ? (
        <JournalPage onBack={() => (window.location.hash = "")} />
      ) : view === "finance" ? (
        <FinancePage onBack={() => (window.location.hash = "")} />
      ) : view === "consult" ? (
        <ConsultPage />
      ) : (
        <TodayPage onOpenDebug={() => (window.location.hash = "#debug")} />
      )}
      {/* 全画面に常設のナビ(各ページが .pb-nav で下余白を確保) */}
      <BottomNav current={view} />
    </>
  );
}
