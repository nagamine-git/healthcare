/** 良い行動(garden / becoming)の種別ラベル。各所の重複を一元化。 */
export const KIND_LABEL: Record<string, string> = {
  coding: "コーディング",
  exercise: "運動",
  meditation: "瞑想",
  journaling: "ジャーナリング",
  reflection: "内省",
};

export function kindLabel(kind: string): string {
  return KIND_LABEL[kind] ?? kind;
}
