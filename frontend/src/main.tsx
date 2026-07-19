import React from "react";
import ReactDOM from "react-dom/client";
import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import { UnsavedGuard } from "./components/UnsavedGuard";
import "./index.css";

// ビルド識別子を window に公開 (ネイティブシェルの設定画面が読んで「読込中のUI版」を表示)。
declare const __ASCEND_BUILD__: string;
declare const __ASCEND_SHA__: string;
(window as unknown as { __ASCEND_BUILD__: string }).__ASCEND_BUILD__ = __ASCEND_BUILD__;
(window as unknown as { __ASCEND_SHA__: string }).__ASCEND_SHA__ = __ASCEND_SHA__;

// どこか1箇所でも更新 (mutation 成功) したら、表示中の全クエリを再取得する。
// invalidateQueries はデフォルトで active (マウント中) のクエリだけ refetch
// するので、「必要な箇所だけ」自動更新される (カフェイン記録→今日の流れ等)。
//
// ただし「調子」のドット連打のように短時間に何度も更新すると、その都度
// 全クエリ (today 等の重い再計算を含む) を取り直して固まる。成功をまとめて
// 1 回だけ invalidate するようデバウンスする (連打中は裏で走らせない)。
const INVALIDATE_DEBOUNCE_MS = 500;
let invalidateTimer: ReturnType<typeof setTimeout> | undefined;
const queryClient = new QueryClient({
  mutationCache: new MutationCache({
    onSuccess: () => {
      if (invalidateTimer) clearTimeout(invalidateTimer);
      invalidateTimer = setTimeout(() => {
        invalidateTimer = undefined;
        queryClient.invalidateQueries();
      }, INVALIDATE_DEBOUNCE_MS);
    },
  }),
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      refetchOnWindowFocus: true,
    },
  },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <UnsavedGuard />
      <App />
    </QueryClientProvider>
  </React.StrictMode>
);
