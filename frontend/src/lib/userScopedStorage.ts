/**
 * Browser storage that belongs to ONE signed-in account (#756).
 *
 * On a shared browser, whatever the previous student left in localStorage /
 * sessionStorage is read by the next one: their active semester, an
 * onboarding draft with their courses, a quiz in progress, their tutor
 * privacy toggle. `clearUserScopedStorage` wipes it whenever this browser's
 * identity ends or changes — sign-out, account deletion, a dead session
 * (UserContext's clearStaleClientAuth) and a sign-in as someone else.
 *
 * Purely device-level UI preferences stay (sidebar collapsed, list/grid
 * layout, graph mode, tutor rail open, the landing animation): they say
 * nothing about the person. A new per-user key belongs in the lists below.
 */

/** localStorage keys holding one account's data or choices. */
export const USER_SCOPED_LOCAL_KEYS = [
  'sapling_user', // identity (UserContext)
  'sapling_active_semester', // lib/useActiveSemester.ts
  'sapling_onboarding_draft', // Onboarding.tsx's legacy shared draft (pre-#757)
  'sapling_quiz_session', // lib/quiz/session.ts
  'sapling_quiz_prefs', // lib/quiz/session.ts + prefs.ts
  'sapling_quiz_dismissed', // lib/quiz/session.ts
  'sapling_concept_descriptions_v2', // lib/quiz/conceptDescriptions.ts (from the student's uploads)
  'sapling_concept_descriptions_v1', // its legacy unkeyed store
  'sapling_shared_ctx', // chat/SharedContextToggle.tsx (a privacy choice)
  'sapling_model_pref', // chat/ModelToggle.tsx
  'ach:seen-ids', // screens/Achievements.tsx
  'sapling_last_feedback', // lib/feedbackPacing.ts: pulse (FeedbackFlow.tsx) cooldown
  'sapling_last_session_feedback', // lib/feedbackPacing.ts: session prompt cooldown
  'sapling_feedback_sessions', // lib/feedbackPacing.ts: sessions that had a prompt
  'sapling_session_end_count', // Learn.tsx / SessionFeedbackFlow.tsx
  'sapling_disclaimer_ack', // DisclaimerModal.tsx (each student acknowledges)
] as const;

/** localStorage key prefixes (one key per account). */
export const USER_SCOPED_LOCAL_PREFIXES = [
  'sapling_onboarding_draft:', // Onboarding.tsx onboardingDraftKey(userId), #757
  'sapling.flags.v1:', // context/FlagsContext.tsx last-known flags per user, #771
] as const;

/** sessionStorage keys holding one account's data. */
export const USER_SCOPED_SESSION_KEYS = [
  'sapling_last_session_context', // lib/feedbackPacing.ts ended session: LoopLearn / Learn.tsx → SessionFeedbackGlobal.tsx
  'sapling_pending_token', // lib/pendingToken.ts
] as const;

/** sessionStorage key prefixes (one key per course). */
export const USER_SCOPED_SESSION_PREFIXES = [
  'gb-cats-', // screens/Gradebook/Course.tsx
] as const;

function keysOf(storage: Storage): string[] {
  const keys: string[] = [];
  for (let i = 0; i < storage.length; i++) {
    const key = storage.key(i);
    if (key !== null) keys.push(key);
  }
  return keys;
}

/** Remove every user-scoped key. Never throws (storage may be unavailable). */
export function clearUserScopedStorage(): void {
  if (typeof window === 'undefined') return;
  try {
    const local = window.localStorage;
    for (const key of USER_SCOPED_LOCAL_KEYS) local.removeItem(key);
    for (const key of keysOf(local)) {
      if (USER_SCOPED_LOCAL_PREFIXES.some((prefix) => key.startsWith(prefix))) {
        local.removeItem(key);
      }
    }
  } catch {}
  try {
    const session = window.sessionStorage;
    for (const key of USER_SCOPED_SESSION_KEYS) session.removeItem(key);
    for (const key of keysOf(session)) {
      if (USER_SCOPED_SESSION_PREFIXES.some((prefix) => key.startsWith(prefix))) {
        session.removeItem(key);
      }
    }
  } catch {}
}
