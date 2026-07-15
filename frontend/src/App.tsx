import { useEffect, useState } from "react";
import { TodayPage } from "./pages/Today";
import { DebugPage } from "./pages/Debug";
import { CompassPage, type CompassSegment } from "./pages/Compass";
import { CheckupPage } from "./pages/Checkup";
import { JournalPage } from "./pages/Journal";
import { FinancePage } from "./pages/Finance";
import { ConsultPage } from "./pages/Consult";
import { BottomNav } from "./components/ui/BottomNav";
import { QuickLogSheet } from "./components/QuickLogSheet";

type View = "home" | "debug" | "compass" | "checkup" | "journal" | "finance" | "consult";

// 旧ハッシュ(#identity/#life/#becoming/#garden)は統合された羅針盤の各セグメントへ着地させる。
// #becoming(歩み・到達予測)は廃止 → 目的・領域へ着地。
const COMPASS_HASHES: Record<string, CompassSegment> = {
  "#compass": "values",
  "#identity": "values",
  "#life": "purpose",
  "#becoming": "purpose",
  "#garden": "garden",
};

function viewFromHash(): View {
  const h = window.location.hash;
  if (h === "#debug") return "debug";
  if (h in COMPASS_HASHES) return "compass";
  if (h === "#checkup") return "checkup";
  if (h === "#journal") return "journal";
  if (h === "#finance") return "finance";
  if (h.startsWith("#consult")) return "consult"; // #consult?prefill=... も相談へ
  return "home"; // #tab-xxx は Today 内タブ指定として Today が解釈する
}

export default function App() {
  const [view, setView] = useState<View>(viewFromHash);
  const [compassSeg, setCompassSeg] = useState<CompassSegment>(
    COMPASS_HASHES[window.location.hash] ?? "values",
  );
  const [quickLogOpen, setQuickLogOpen] = useState(false);

  useEffect(() => {
    // #quicklog はクイック記録シートを開く特殊ルート (ネイティブシェルのショートカット用)
    const maybeOpenQuickLog = () => {
      if (window.location.hash === "#quicklog") {
        window.location.hash = "";
        setQuickLogOpen(true);
        return true;
      }
      return false;
    };
    const handler = () => {
      if (maybeOpenQuickLog()) return;
      setView(viewFromHash());
      setCompassSeg(COMPASS_HASHES[window.location.hash] ?? "values");
      setQuickLogOpen(false); // 画面遷移でシートは閉じる
    };
    maybeOpenQuickLog(); // 初回ロード分
    window.addEventListener("hashchange", handler);
    // 「いまコレ」等の任意コンポーネントからクイック記録シートを開けるイベント
    const openQuickLog = () => setQuickLogOpen(true);
    window.addEventListener("open-quicklog", openQuickLog);
    return () => {
      window.removeEventListener("hashchange", handler);
      window.removeEventListener("open-quicklog", openQuickLog);
    };
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
      <BottomNav current={view} onQuickLog={() => setQuickLogOpen(true)} />
      <QuickLogSheet open={quickLogOpen} onClose={() => setQuickLogOpen(false)} />
    </>
  );
}
