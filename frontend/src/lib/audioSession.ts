/**
 * iOS のサイレントスイッチ対策。Web Audio はサイレントモードで消音されるが、
 * AudioSession API で type を宣言すると鳴らせる。
 * - "playback": サイレントでもスピーカーで再生 (メトロノームなど録音なしの用途)
 * - "play-and-record": マイク録音と同時再生 (椅子テストの手拍子検出+ビープ)
 * 非対応ブラウザ (iOS 16.3 以前 / 一部) では無害な no-op。
 * https://developer.mozilla.org/en-US/docs/Web/API/AudioSession
 */
export type AudioSessionType = "playback" | "play-and-record" | "auto";

export function setAudioSession(type: AudioSessionType): void {
  const ns = navigator as unknown as { audioSession?: { type: string } };
  if (ns.audioSession) {
    try {
      ns.audioSession.type = type;
    } catch {
      // 値非対応などは無視 (現状の挙動を維持)。
    }
  }
}
