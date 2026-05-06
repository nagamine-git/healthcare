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

  if (view === "debug") {
    return (
      <DebugPage
        onBack={() => {
          window.location.hash = "";
        }}
      />
    );
  }

  return <TodayPage onOpenDebug={() => (window.location.hash = "#debug")} />;
}
