/** 良い行動(garden / becoming)の種別ラベル。各所の重複を一元化。 */
export const KIND_LABEL: Record<string, string> = {
  // 認知・創造
  coding: "コーディング",
  creative: "制作・発信",
  deepwork: "ディープワーク",
  reading: "読書",
  learning: "学習",
  cultural_input: "教養インプット",
  teaching: "教える・共有",
  planning: "計画・週次レビュー",
  // 身体
  aerobic: "有酸素運動",
  strength: "筋トレ",
  sleep: "十分な睡眠",
  steps: "よく歩く",
  nature: "自然・朝日",
  mobility: "ストレッチ",
  healthy_meal: "整った食事",
  // メンタル・内省
  meditation: "瞑想",
  journaling: "ジャーナリング",
  reflection: "内省",
  gratitude: "感謝の記録",
  music: "音楽で整える",
  breathwork: "呼吸を整える",
  digital_detox: "デジタル断ち",
  tidying: "環境整備",
  // 人・生活
  social: "人に会う",
  family: "家族の時間",
  finance: "家計・投資",
};

export function kindLabel(kind: string): string {
  return KIND_LABEL[kind] ?? kind;
}
