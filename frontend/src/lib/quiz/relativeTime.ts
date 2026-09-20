/**
 * "last studied 4 days ago" — the phrase the quiz home's meta lines are built
 * from.
 *
 * The frontend had no relative-time formatter at all before #537 (the tree
 * printed a raw `toLocaleString()` or the word "never", R4 §3). Counting is
 * done in CALENDAR days, not 24-hour blocks: something studied at 11pm
 * yesterday reads "yesterday" this morning, which is what a person means.
 */

const MS_PER_DAY = 24 * 60 * 60 * 1000;

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

/**
 * Whole calendar days between `iso` and `now` (0 = today, 1 = yesterday).
 * Returns `null` for an absent or unparseable timestamp. A future timestamp
 * clamps to 0 rather than going negative — clock skew is not a story to tell.
 */
export function daysAgo(iso: string | null | undefined, now: Date = new Date()): number | null {
  if (!iso) return null;
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return null;
  const days = Math.round((startOfDay(now) - startOfDay(then)) / MS_PER_DAY);
  return days < 0 ? 0 : days;
}

/** The phrase for a `last_studied_at`: "today" | "yesterday" | "N days ago" |
 *  "not studied yet". */
export function relativeStudied(
  iso: string | null | undefined,
  now: Date = new Date(),
): string {
  const days = daysAgo(iso, now);
  if (days === null) return "not studied yet";
  if (days === 0) return "today";
  if (days === 1) return "yesterday";
  return `${days} days ago`;
}
