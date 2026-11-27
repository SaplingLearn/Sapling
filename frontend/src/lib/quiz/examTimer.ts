/**
 * W7.8 Exam Twin client timer — display only.
 * Soft countdown; does not auto-submit (student finishes Check/Leave).
 */

/** Seconds for a dress rehearsal: 90s per question, floored at 3 minutes. */
export function examTwinDurationSeconds(questionCount: number): number {
  const n = Number.isFinite(questionCount) ? Math.max(1, Math.floor(questionCount)) : 1;
  return Math.max(180, n * 90);
}

export function formatExamClock(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${r.toString().padStart(2, "0")}`;
}
