/**
 * Where onboarding keeps a half-finished set of answers in this browser.
 *
 * One key per account (#757), written as the student goes and removed when
 * the profile is saved, when the browser's identity ends (sign-out, a dead
 * session, a sign-in as someone else: lib/userScopedStorage.ts clears every
 * `sapling_onboarding_draft:` key) and once it is DRAFT_TTL_MS old, so a
 * computer that stays signed in doesn't keep someone's answers for long.
 *
 * Onboarding needs an account (sign in first): the answers a signed-out
 * visitor used to leave under the `guest` key by the landing-page takeover are
 * purged on every page load (UserProvider calls purgeGuestOnboardingDraft).
 */

const PREFIX = "sapling_onboarding_draft";

/** A draft older than this is dropped unread. */
export const DRAFT_TTL_MS = 7 * 24 * 60 * 60 * 1000;
/** A draft stamped a little in the future (a clock set back) still counts. */
const CLOCK_SKEW_MS = 60 * 1000;

export function onboardingDraftKey(userId: string): string {
  return `${PREFIX}:${userId}`;
}

/** The key the removed guest flow wrote before sign-in. */
export const GUEST_DRAFT_KEY = onboardingDraftKey("guest");

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function fresh(record: Record<string, unknown>, now: number): boolean {
  const savedAt = record.savedAt;
  if (typeof savedAt !== "number") return false;
  const age = now - savedAt;
  return age >= -CLOCK_SKEW_MS && age < DRAFT_TTL_MS;
}

/**
 * The account's stored draft, without its timestamp, or null. A draft that is
 * missing, unreadable, unstamped (written before the expiry existed) or
 * expired is removed and reads as null. Also drops the pre-#757 key, which
 * every account on the browser shared.
 */
export function readOnboardingDraft(userId: string, now = Date.now()): Record<string, unknown> | null {
  if (typeof window === "undefined" || !userId) return null;
  try {
    localStorage.removeItem(PREFIX);
    const raw = localStorage.getItem(onboardingDraftKey(userId));
    if (raw === null) return null;
    const record = asRecord(JSON.parse(raw));
    if (record && fresh(record, now)) {
      const draft = { ...record };
      delete draft.savedAt;
      return draft;
    }
  } catch {}
  clearOnboardingDraft(userId);
  return null;
}

/** Stores the account's draft, stamped with `now` for the expiry. */
export function writeOnboardingDraft(userId: string, draft: object, now = Date.now()): void {
  try {
    localStorage.setItem(onboardingDraftKey(userId), JSON.stringify({ ...draft, savedAt: now }));
  } catch {}
}

export function clearOnboardingDraft(userId: string): void {
  try {
    localStorage.removeItem(onboardingDraftKey(userId));
  } catch {}
}

/** Removes whatever a signed-out visitor's guest onboarding left behind. */
export function purgeGuestOnboardingDraft(): void {
  try {
    localStorage.removeItem(GUEST_DRAFT_KEY);
  } catch {}
}
