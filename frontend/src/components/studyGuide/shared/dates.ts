/**
 * A due date, as both study-guide screens read and word it. A due date is a
 * calendar day, so it is read as written: no timezone moves it.
 */

/** A `YYYY-MM-DD` (or ISO) date as UTC midnight, or null when it is not one. */
export function dueDay(date: string | null): number | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(date ?? "");
  if (!match) return null;
  return Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
}

/** "Wed, Nov 18", or "" when there is no date. */
export function dueDateText(date: string | null): string {
  const due = dueDay(date);
  if (due === null) return "";
  return new Date(due).toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}
