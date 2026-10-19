import type { LoopGoal } from "./api";

/** One explicit Begin check-in click, not an account preference or saved goal. */
export interface OnboardingLearningIntent {
  version: 1;
  id: string;
  userId: string;
  courseId: string;
  createdAt: number;
  goal: LoopGoal | null;
  /** Accepted lazy opener: reuse this ID until its first probe persists it. */
  startedSessionId?: string;
}

export const ONBOARDING_INTENT_TTL_MS = 24 * 60 * 60 * 1000;
export const hrefOnboardingLearning = (courseId: string) => `/learn?course=${encodeURIComponent(courseId)}`;
const keyFor = (userId: string) => `sapling:onboarding-learning:v1:${encodeURIComponent(userId)}`;
const validId = (value: unknown): value is string => typeof value === "string" && value.trim() === value && value.length > 0 && value.length <= 256;
const validGoal = (goal: unknown): goal is LoopGoal | null => {
  if (goal === null) return true;
  if (typeof goal !== "object" || !goal) return false;
  const candidate = goal as Partial<LoopGoal>;
  return typeof candidate.text === "string" && candidate.text.length <= 500 &&
    Array.isArray(candidate.target_node_ids) && candidate.target_node_ids.length >= 1 && candidate.target_node_ids.length <= 12 &&
    candidate.target_node_ids.every(validId) && new Set(candidate.target_node_ids).size === candidate.target_node_ids.length;
};

function parse(value: unknown, now = Date.now()): OnboardingLearningIntent | null {
  if (!value || typeof value !== "object") return null;
  const candidate = value as Partial<OnboardingLearningIntent>;
  if (candidate.version !== 1 || !validId(candidate.id) || !validId(candidate.userId) || !validId(candidate.courseId) ||
    typeof candidate.createdAt !== "number" || !Number.isFinite(candidate.createdAt) || candidate.createdAt > now + 60_000 ||
    now - candidate.createdAt >= ONBOARDING_INTENT_TTL_MS || !validGoal(candidate.goal) ||
    (candidate.startedSessionId !== undefined && !validId(candidate.startedSessionId))) return null;
  return {
    version: 1, id: candidate.id, userId: candidate.userId, courseId: candidate.courseId, createdAt: candidate.createdAt,
    goal: candidate.goal ? { text: candidate.goal.text.trim(), target_node_ids: [...candidate.goal.target_node_ids] } : null,
    ...(candidate.startedSessionId ? { startedSessionId: candidate.startedSessionId } : {}),
  };
}

/** Called only by the onboarding review screen's explicit Begin action. */
export function writeOnboardingIntent({ userId, courseId, goal }: { userId: string; courseId: string; goal: LoopGoal | null }): boolean {
  if (typeof window === "undefined") return false;
  const intent = parse({ version: 1, id: `${Date.now()}-${Math.random().toString(36).slice(2)}`, userId, courseId, goal, createdAt: Date.now() });
  if (!intent) return false;
  try {
    window.sessionStorage.setItem(keyFor(userId), JSON.stringify(intent));
    return true;
  } catch { return false; }
}

/** Discover this account's pending course after /learn cleans its deep link. */
export function readOnboardingIntentForUser(userId: string): OnboardingLearningIntent | null {
  if (typeof window === "undefined" || !validId(userId)) return null;
  try {
    const stored = window.sessionStorage.getItem(keyFor(userId));
    if (!stored) return null;
    const intent = parse(JSON.parse(stored));
    if (!intent || intent.userId !== userId) {
      window.sessionStorage.removeItem(keyFor(userId));
      return null;
    }
    return intent;
  } catch { return null; }
}

export function readOnboardingIntent(userId: string, courseId: string): OnboardingLearningIntent | null {
  if (!validId(courseId)) return null;
  const intent = readOnboardingIntentForUser(userId);
  return intent?.courseId === courseId ? intent : null;
}

export function recordOnboardingSession(intent: OnboardingLearningIntent, sessionId: string): OnboardingLearningIntent | null {
  const current = readOnboardingIntent(intent.userId, intent.courseId);
  if (current?.id !== intent.id || !validId(sessionId)) return null;
  const accepted = { ...current, startedSessionId: sessionId };
  try { window.sessionStorage.setItem(keyFor(intent.userId), JSON.stringify(accepted)); return accepted; }
  catch { return null; }
}

/** A late response cannot clear a newer Begin click for the same account. */
export function clearOnboardingIntent(intent: OnboardingLearningIntent): void {
  const current = readOnboardingIntent(intent.userId, intent.courseId);
  if (current?.id !== intent.id) return;
  try { window.sessionStorage.removeItem(keyFor(intent.userId)); } catch { /* A successful server operation is still successful. */ }
  // The review screen tags its checkpoint with this exact Begin click. Keep
  // a newer draft, another account, or an unknown draft version untouched.
  try {
    const checkpointKey = `sapling_onboarding_v3:${intent.userId}`;
    const raw = window.localStorage.getItem(checkpointKey);
    if (!raw) return;
    const checkpoint = JSON.parse(raw);
    if (checkpoint.version === 3 && checkpoint.userId === intent.userId && checkpoint.handoffId === intent.id) {
      window.localStorage.removeItem(checkpointKey);
    }
  } catch { /* The server operation must not be replayed because local cleanup failed. */ }
}

/** Recheck against current server enrollment and graph, never objective text. */
export function isOnboardingIntentScopeValid(
  intent: OnboardingLearningIntent,
  userId: string,
  courseId: string,
  enrolledCourseIds: readonly string[],
  concepts: readonly { id: string; course_id?: string | null; is_subject_root?: boolean; mastery_tier?: string }[],
): boolean {
  if (!parse(intent) || intent.userId !== userId || intent.courseId !== courseId || !enrolledCourseIds.includes(courseId)) return false;
  const available = new Set(concepts.filter((node) => node.course_id === courseId && !node.is_subject_root && node.mastery_tier !== "subject_root").map((node) => node.id));
  return intent.goal === null || intent.goal.target_node_ids.every((id) => available.has(id));
}
