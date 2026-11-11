/**
 * Pure view helpers for the Gradescope connect/sync dialog: its stage list,
 * the heading per stage, when it may be dismissed, and the settings-mode
 * "connected" copy. Kept beside gradescopeState.ts for the same reason: no
 * import of `lib/api` values, so tests that mock that module whole still work.
 */

export type Stage =
  | "loading"
  | "verification-error"
  | "choose-mode"
  | "credentials"
  | "cookies"
  | "bu-sso-form"
  | "bu-sso-waiting"
  | "connected" // settings-mode: creds saved, no course to sync
  | "link"
  | "ready"
  | "syncing"
  | "done";

const DEFAULT_TITLE = "Pull grades from Gradescope";

const STAGE_TITLES = {
  "loading": DEFAULT_TITLE,
  "verification-error": "Couldn't verify Gradescope",
  "choose-mode": "Connect Gradescope",
  "credentials": "Sign in with Gradescope password",
  "cookies": "Paste your Gradescope session",
  "bu-sso-form": "Sign in with BU SSO",
  "bu-sso-waiting": "Waiting for Duo approval",
  "connected": "Gradescope is connected",
  "link": "Pick the matching Gradescope course",
  "ready": DEFAULT_TITLE,
  "syncing": DEFAULT_TITLE,
} satisfies Record<Exclude<Stage, "done">, string>;

/** The dialog heading. "done" depends on whether any assignment failed. */
export function gradescopeDialogTitle(stage: Stage, result: { failed: number } | null): string {
  if (stage === "done") return result?.failed ? "Sync needs attention" : "Sync complete";
  return STAGE_TITLES[stage];
}

/** Backdrop click / Escape may close the dialog only when nothing would be
 *  cut off: no save in flight, no sync still owed an answer (a queued sync
 *  that went pending may be left running), and no Duo push being awaited. */
export function canDismissGradescopeDialog(stage: Stage, saving: boolean, syncPending: boolean): boolean {
  return !saving && (stage !== "syncing" || syncPending) && stage !== "bu-sso-waiting";
}

/** Settings-mode copy once saved credentials were verified by a live listing. */
export function connectedCopy(courseCount: number): string {
  return courseCount > 0
    ? `Your Gradescope account is verified with ${courseCount} student course${courseCount === 1 ? "" : "s"}. Go to a course in the gradebook to link it and sync grades.`
    : "Sign-in was verified, but this account has no student courses. Check that you used the same Gradescope account you use for your classes.";
}
