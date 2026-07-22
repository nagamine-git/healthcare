import { useEffect, useState } from "react";
import { refreshPalette } from "./palette";

/// テーマ選好。system は端末の外観に追従、light/dark は固定。
export type ThemePref = "system" | "light" | "dark";

const KEY = "healthcare:theme";
const DARK_THEME_COLOR = "#0a0e14"; // ダーク時の status bar / PWA テーマ色
const LIGHT_THEME_COLOR = "#eceff3"; // ライト時 (--c-void 相当)

/// 選好を実際のテーマ (light|dark) に解決する。system は matchMedia を見る。
function resolve(pref: ThemePref): "light" | "dark" {
  if (pref !== "system") return pref;
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

/// <html data-theme> と theme-color meta を実テーマに合わせる。
/// index.html のインラインスクリプトと**同じ規約**なので、初回描画後もブレない。
function apply(pref: ThemePref): void {
  const actual = resolve(pref);
  document.documentElement.dataset.theme = actual;
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) {
    meta.setAttribute("content", actual === "light" ? LIGHT_THEME_COLOR : DARK_THEME_COLOR);
  }
  // data-theme を変えた後に、Recharts/SVG が読む TS パレットも更新する。
  refreshPalette();
}

function read(): ThemePref {
  try {
    const v = localStorage.getItem(KEY);
    if (v === "light" || v === "dark" || v === "system") return v;
  } catch {
    /* localStorage 不可でも既定で動く */
  }
  return "system";
}

/// テーマ選好の読み書きフック。system 選択中は端末テーマの変化に追従する。
export function useTheme(): [ThemePref, (p: ThemePref) => void] {
  const [pref, setPref] = useState<ThemePref>(read);

  useEffect(() => {
    apply(pref);
    try {
      localStorage.setItem(KEY, pref);
    } catch {
      /* 保存できなくても表示は効く */
    }
    if (pref !== "system") return;
    // system のときだけ、端末の外観切替に追従する。
    const mq = window.matchMedia("(prefers-color-scheme: light)");
    const onChange = () => apply("system");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [pref]);

  return [pref, setPref];
}
