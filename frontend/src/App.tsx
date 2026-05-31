import { useEffect, useState } from "react";
import { TodayPage } from "./pages/Today";
import { DebugPage } from "./pages/Debug";
import { TrendsPage } from "./pages/Trends";

type View = "today" | "debug" | "trends";

function viewFromHash(): View {
  if (window.location.hash === "#debug") return "debug";
  if (window.location.hash === "#trends") return "trends";
  return "today";
}

export default function App() {
  const [view, setView] = useState<View>(viewFromHash);

  useEffect(() => {
    const handler = () => setView(viewFromHash());
    window.addEventListener("hashchange", handler);
    return () => window.removeEventListener("hashchange", handler);
  }, []);

  if (view === "debug") {
    return (
      <DebugPage
        onBack={() => {
          window.location.hash = "";
        }}
      />
    );
  }

  if (view === "trends") {
    return (
      <TrendsPage
        onBack={() => {
          window.location.hash = "";
        }}
      />
    );
  }

  return <TodayPage onOpenDebug={() => (window.location.hash = "#debug")} />;
}
