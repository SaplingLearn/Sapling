/**
 * The Google Calendar consent flow's way back (backend routes/calendar_connect.py).
 * It is started from onboarding's Connect step or the Calendar page, with a
 * full page load to `calendarAuthUrl`. Either way it lands on its `next` page
 * (default /calendar): with `?connected=true` when it worked, else with
 * `?calendar_error=<code>`, which that page explains with the sentence below
 * (the Calendar page itself; elsewhere `useCalendarConnectError`).
 */
export const CALENDAR_ERROR_PARAM = "calendar_error";

export function calendarConnectError(code: string): string {
  switch (code) {
    case "access_denied":
      return "Google Calendar wasn't connected because access wasn't allowed. You can connect it again any time.";
    case "scope_denied":
      return "Google Calendar wasn't connected: Sapling needs permission to see and add your events. Connect again and allow both.";
    case "google_not_configured":
      return "Google Calendar can't be connected right now.";
    case "calendar_unavailable":
      return "Calendar is currently unavailable for your account.";
    default:
      // invalid_state, missing_code, oauth_exchange_failed, anything new.
      return "Google Calendar couldn't be connected. Please try again.";
  }
}

/** The Google Calendar consent flow: a backend route that redirects to Google,
 * so open it with a full page load (`window.location`), never the in-app
 * router. `next` is where the callback lands after a successful connect; the
 * backend honours only its allowlist (/dashboard, /gradebook, /calendar). */
export const calendarAuthUrl = (userId: string, next?: string) => {
  const params = [`user_id=${encodeURIComponent(userId)}`];
  if (next) params.push(`next=${encodeURIComponent(next)}`);
  if (typeof window !== 'undefined') params.push(`return_to=${encodeURIComponent(window.location.origin)}`);
  return `/api/calendar/auth-url?${params.join('&')}`;
};
