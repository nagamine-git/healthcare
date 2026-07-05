/** File → base64 (data URL のヘッダを除いた本体)。画像OCR取込で共用。 */
export function fileToB64(file: File): Promise<string> {
  return new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => res(String(r.result).split(",")[1] ?? "");
    r.onerror = rej;
    r.readAsDataURL(file);
  });
}
