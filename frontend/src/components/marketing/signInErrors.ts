/**
 * What each sign-in error code means to the student. The codes come from the
 * backend's sign-in error path (routes/auth.py `_fail_redirect`): a same-tab
 * sign-in lands on `/?error=<code>` and the landing opens the sign-in box with
 * it (useSignInErrorParam), a popup sign-in reaches /auth/callback with it and
 * broadcasts it to the box that opened the popup. The callback page shows the
 * same sentence while it closes or routes away.
 */
export const SIGN_IN_ERROR_COPY: Record<string, string> = {
  not_approved: "Your account is pending approval. We'll email you once an admin lets you in.",
  invalid_domain: "Sign-in is limited to approved school accounts (@bu.edu).",
  google_not_configured: "Google sign-in is not configured on the server. Please contact support.",
  signin_failed: "Sign-in failed. Please try again.",
  account_deleted:
    "This account was deleted. If you think that's a mistake, please contact support.",
  session_expired: "Your session has expired. Please sign in again.",
  env_misconfig: "This environment is misconfigured and can't sign you in. Please contact support.",
  revoked: "Your access has been revoked.",
  // The student closed Google's window or chose Cancel on its consent screen.
  cancelled: "Sign-in was cancelled.",
  oauth_denied: "Sign-in was cancelled.",
  unknown: "Something went wrong. Please try again.",
};

export function signInErrorMessage(code: string): string {
  return SIGN_IN_ERROR_COPY[code] ?? `Something went wrong (${code}).`;
}
