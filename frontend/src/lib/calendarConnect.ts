/**
 * The Google Calendar consent flow's way back (backend routes/calendar.py).
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
    default:
      // invalid_state, missing_code, oauth_exchange_failed, anything new.
      return "Google Calendar couldn't be connected. Please try again.";
  }
}
