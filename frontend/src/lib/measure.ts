/** 測定モードの純粋ロジック (副作用なし)。フックから利用し、単体で検証可能に保つ。 */

/** 1拍の秒数。 */
export function bpmToInterval(bpm: number): number {
  return 60 / bpm;
}

/** 腕立て1回 = 2拍 (下げ/上げ) の秒数。 */
export function repIntervalSec(bpm: number): number {
  return bpmToInterval(bpm) * 2;
}

/**
 * 最後のタップから「1回分 + 3拍」経過したら自動停止 (プロトコル「3拍以上遅れたら終了」)。
 * lastTapAt / now は performance.now() ベースのミリ秒、repInterval / beat は秒。
 */
export function shouldAutoStop(
  lastTapAt: number,
  now: number,
  repInterval: number,
  beat: number,
): boolean {
  return (now - lastTapAt) / 1000 > repInterval + 3 * beat;
}

/** 音量が閾値を下から上に跨いだ瞬間 (立ち上がりエッジ) を検出。 */
export function isOnset(level: number, prevLevel: number, threshold: number): boolean {
  return prevLevel < threshold && level >= threshold;
}
