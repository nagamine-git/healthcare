import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "healthcare:geolocation";
const STALE_MS = 6 * 60 * 60 * 1000; // 6h ごとに再取得を促す

export type Coords = {
  lat: number;
  lon: number;
  accuracy: number | null;
  obtained_at: number; // epoch ms
};

type Stored = {
  coords: Coords | null;
  /** ユーザーが明示的に却下した場合、再要求しない */
  denied?: boolean;
};

function readStored(): Stored {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { coords: null };
    return JSON.parse(raw) as Stored;
  } catch {
    return { coords: null };
  }
}

function writeStored(s: Stored): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(s));
  } catch {
    // localStorage 使えない環境は無視
  }
}

export function useGeolocation() {
  const [stored, setStored] = useState<Stored>(() => readStored());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const request = useCallback(() => {
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      setError("このブラウザは Geolocation API に対応していません");
      return;
    }
    setBusy(true);
    setError(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const next: Stored = {
          coords: {
            lat: pos.coords.latitude,
            lon: pos.coords.longitude,
            accuracy: pos.coords.accuracy,
            obtained_at: Date.now(),
          },
          denied: false,
        };
        writeStored(next);
        setStored(next);
        setBusy(false);
      },
      (err) => {
        const denied = err.code === err.PERMISSION_DENIED;
        const next: Stored = {
          coords: stored.coords,
          denied,
        };
        writeStored(next);
        setStored(next);
        setError(
          denied
            ? "位置情報の利用を拒否しました (設定から許可で再取得可)"
            : `取得失敗: ${err.message}`,
        );
        setBusy(false);
      },
      { enableHighAccuracy: false, timeout: 8000, maximumAge: 60 * 1000 },
    );
  }, [stored.coords]);

  const clear = useCallback(() => {
    writeStored({ coords: null, denied: false });
    setStored({ coords: null, denied: false });
    setError(null);
  }, []);

  // 起動時に保存座標が stale なら自動更新を試みる (denied フラグ立ってない場合)
  useEffect(() => {
    const c = stored.coords;
    if (stored.denied) return;
    if (!c) return;
    if (Date.now() - c.obtained_at > STALE_MS) {
      request();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return {
    coords: stored.coords,
    denied: !!stored.denied,
    busy,
    error,
    request,
    clear,
  };
}
