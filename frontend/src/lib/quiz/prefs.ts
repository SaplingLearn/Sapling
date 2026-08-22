/**
 * Remembered quiz settings: length, difficulty, and when the verdict shows.
 *
 * Feedback mode is a client-only concept (R-2, gap G1) — `/api/quiz/config`
 * offers counts, difficulties and question types, and nothing else. The two
 * modes are therefore the ONE list this codebase is allowed to write down;
 * counts and difficulties must always come off the config endpoint.
 *
 * Stored values are validated against the live config at read time, so a
 * remembered "15 questions" from before the ceiling moved can never be sent.
 */

import { PREFS_KEY } from "./session";
import type { FeedbackMode, QuizConfig, QuizPrefs } from "./types";

/** The only hardcoded option list in the quiz (R-2). */
export const FEEDBACK_MODES: readonly FeedbackMode[] = ["as-you-go", "at-end"] as const;

export const FEEDBACK_LABELS: Record<FeedbackMode, string> = {
  "as-you-go": "As you go",
  "at-end": "At the end",
};

export const DEFAULT_PREFS: QuizPrefs = { count: null, difficulty: null, feedback: "at-end" };

function isFeedbackMode(value: unknown): value is FeedbackMode {
  return typeof value === "string" && (FEEDBACK_MODES as readonly string[]).includes(value);
}

/**
 * Reads stored prefs. `config` is optional: pass it and a remembered value the
 * server would now reject is dropped back to "no preference" rather than
 * silently producing a 400 on the next generate.
 */
export function loadPrefs(config?: QuizConfig | null): QuizPrefs {
  let raw: unknown = null;
  try {
    if (typeof window !== "undefined") {
      const text = window.localStorage.getItem(PREFS_KEY);
      raw = text ? JSON.parse(text) : null;
    }
  } catch {
    raw = null;
  }
  if (raw === null || typeof raw !== "object") return { ...DEFAULT_PREFS };

  const stored = raw as Partial<QuizPrefs>;
  const count = typeof stored.count === "number" && Number.isFinite(stored.count)
    ? stored.count
    : null;
  const difficulty = typeof stored.difficulty === "string" && stored.difficulty
    ? stored.difficulty
    : null;

  return {
    count: config && count !== null && !config.num_questions.options.includes(count) ? null : count,
    difficulty:
      config && difficulty !== null && !config.difficulties.includes(difficulty)
        ? null
        : difficulty,
    feedback: isFeedbackMode(stored.feedback) ? stored.feedback : DEFAULT_PREFS.feedback,
  };
}

export function savePrefs(prefs: QuizPrefs): void {
  try {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
  } catch {
    // A forgotten preference is a downgrade, never a failure.
  }
}

export function clearPrefs(): void {
  try {
    if (typeof window !== "undefined") window.localStorage.removeItem(PREFS_KEY);
  } catch {
    // See above.
  }
}
