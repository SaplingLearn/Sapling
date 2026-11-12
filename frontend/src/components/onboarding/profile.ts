/**
 * Finishing onboarding: the profile save (POST /api/onboarding/profile), what
 * each way it can fail means for the student, and where they go after it.
 */
import { calendarAuthUrl, submitOnboardingProfile } from "@/lib/api";
import { errorCodeOf, humanizeError, statusOf } from "@/lib/errorMessage";
import { PRIVACY_VERSION, TERMS_VERSION } from "@/lib/legal/versions";
import type { ConnChoices } from "./flow";
import type { Draft } from "./draft";

/** The save gives up after this long and says so, instead of a hung outro. */
export const SAVE_TIMEOUT_MS = 15_000;
const NAME_MAX = 80;

/**
 * The name field asks for the name to call the student by. The account's
 * name (from Google) supplies the last name; when the student typed their
 * whole name anyway ("Ada Lovelace"), the last name is taken off the end so
 * the saved name isn't "Ada Lovelace Lovelace". A field holding only the last
 * name keeps it as the first name, with no last name after it.
 */
export function splitName(typed: string, accountName: string): { first_name: string; last_name: string } {
  const name = typed.trim().replace(/\s+/g, " ").slice(0, NAME_MAX).trim();
  const last = accountName.trim().split(/\s+/).slice(1).join(" ").slice(0, NAME_MAX).trim();
  if (!last || name.toLowerCase() === last.toLowerCase()) return { first_name: name, last_name: "" };
  const tail = ` ${last}`;
  if (name.length > tail.length && name.slice(-tail.length).toLowerCase() === tail.toLowerCase()) {
    return { first_name: name.slice(0, -tail.length).trim(), last_name: last };
  }
  return { first_name: name, last_name: last };
}

export class SaveTimeoutError extends Error {
  constructor() {
    super("The profile save timed out.");
    this.name = "SaveTimeoutError";
  }
}

/** Saves the profile, or rejects (with SaveTimeoutError after SAVE_TIMEOUT_MS). */
export async function saveProfile({ userId, accountName, draft, under18 }: {
  userId: string;
  accountName: string;
  draft: Draft;
  under18: boolean;
}): Promise<void> {
  const ctrl = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  // Rejects before aborting, so the race settles on the timeout rather than
  // on the fetch's own AbortError.
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      reject(new SaveTimeoutError());
      ctrl.abort();
    }, SAVE_TIMEOUT_MS);
  });
  try {
    await Promise.race([
      submitOnboardingProfile(
        {
          user_id: userId,
          ...splitName(draft.name, accountName),
          year: draft.year,
          course_ids: draft.coursesLater ? [] : draft.courses.map(c => c.id),
          under_18: under18,
          accepted_terms_version: TERMS_VERSION,
          accepted_privacy_version: PRIVACY_VERSION,
        },
        { signal: ctrl.signal },
      ),
      timeout,
    ]);
  } finally {
    clearTimeout(timer);
  }
}

export type SaveFailure =
  /** 409: this account finished onboarding already (another tab, a stale page). */
  | { kind: "already" }
  /** 403 not_approved: the account isn't (or is no longer) let in. */
  | { kind: "not_approved" }
  /** 422 no_known_courses: none of the picked courses exist any more. */
  | { kind: "courses" }
  /** 422 legal_outdated: the Terms or Privacy Policy changed since the page loaded. */
  | { kind: "legal" }
  | { kind: "error"; message: string };

export function classifySaveError(err: unknown): SaveFailure {
  const status = statusOf(err);
  const code = errorCodeOf(err);
  if (status === 409) return { kind: "already" };
  if (status === 403 && code === "not_approved") return { kind: "not_approved" };
  if (status === 422 && code === "no_known_courses") return { kind: "courses" };
  if (status === 422 && code === "legal_outdated") return { kind: "legal" };
  if (err instanceof SaveTimeoutError) {
    return { kind: "error", message: "Saving took too long. Check your connection and try again." };
  }
  return { kind: "error", message: humanizeError(err, "We couldn't save your profile. Please try again.") };
}

/** Where the student goes next: an in-app route, or a full page load. */
export type Handoff = { route: string } | { page: string };

/**
 * After a successful save. Google Calendar's consent flow is a full page load
 * (the backend redirects to Google); it brings the student back to the
 * Gradebook when they chose Gradescope too, where they sign in to it.
 */
export function handoffFor(userId: string, conn: ConnChoices): Handoff {
  if (conn.gcal) return { page: calendarAuthUrl(userId, conn.gradescope ? "/gradebook" : undefined) };
  return { route: conn.gradescope ? "/gradebook" : "/dashboard" };
}
