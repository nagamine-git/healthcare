/**
 * 相談AIハブ化 (Phase 4): 任意の画面から文脈付きで相談タブを開く。
 * ConsultChat が #consult?prefill=... を初期入力として消費する。
 */
export function askAi(prompt: string) {
  window.location.hash = `#consult?prefill=${encodeURIComponent(prompt)}`;
}
