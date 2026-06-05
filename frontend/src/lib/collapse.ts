import { useEffect, useState } from "react";

/**
 * localStorage で永続化される折りたたみ状態フック。
 *
 * @param key 一意なキー (例: "panel:focus")
 * @param defaultOpen デフォルトの開閉状態
 */
export function useCollapse(key: string, defaultOpen: boolean) {
  const storageKey = `healthcare:collapse:${key}`;
  const [open, setOpen] = useState<boolean>(() => {
    try {
      const v = localStorage.getItem(storageKey);
      if (v === null) return defaultOpen;
      return v === "1";
    } catch {
      return defaultOpen;
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(storageKey, open ? "1" : "0");
    } catch {
      // ignore
    }
  }, [open, storageKey]);
  return [open, setOpen] as const;
}
