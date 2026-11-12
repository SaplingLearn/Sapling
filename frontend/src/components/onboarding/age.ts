/**
 * The birthday screen's arithmetic and its under-13 memory.
 *
 * The birthday is only used here, in the browser, to check the student's age
 * and whether they are under 18 (onboarding then sends `under_18`). It is
 * never sent to the server.
 */

export function ageOn(today: Date, m: string, d: string, y: string): number | null {
  if (!m || !d || !y) return null;
  let a = today.getFullYear() - Number(y);
  const month = today.getMonth() + 1;
  if (month < Number(m) || (month === Number(m) && today.getDate() < Number(d))) a--;
  return a;
}

export function isUnder13(age: number | null): boolean {
  return age !== null && age < 13;
}

export function isMinor(age: number | null): boolean {
  return age !== null && age >= 13 && age < 18;
}

/** Days in month `m` (1-12) of year `y`. Before a year is picked it counts a
 * leap year, so 29 February stays available until the year rules it out. */
export function daysInMonth(m: string, y: string): number {
  if (!m) return 31;
  return new Date(y ? Number(y) : 2000, Number(m), 0).getDate();
}

/** The picked day, or "" once the month and year no longer have it. */
export function keepDay(d: string, m: string, y: string): string {
  return d && Number(d) > daysInMonth(m, y) ? "" : d;
}

export function dayOptions(m: string, y: string): [string, string][] {
  return Array.from({ length: daysInMonth(m, y) }, (_, i) => [String(i + 1), String(i + 1)]);
}

/** How far back the year list goes. */
export const YEAR_SPAN = 100;

export function yearOptions(today = new Date()): [string, string][] {
  const thisYear = today.getFullYear();
  return Array.from({ length: YEAR_SPAN + 1 }, (_, i) => [String(thisYear - i), String(thisYear - i)]);
}

/**
 * An under-13 answer is remembered in this browser for AGE_GATE_MS, so going
 * straight back and picking an older year doesn't get round it. Deliberately
 * not per account and not cleared by sign-out (lib/userScopedStorage.ts leaves
 * it alone): signing in as someone else on the same browser doesn't reset it
 * either. Only the expiry time is stored, nothing about the person.
 */
const AGE_GATE_KEY = "sapling_age_gate_until";
export const AGE_GATE_MS = 24 * 60 * 60 * 1000;

export function rememberUnder13(now = Date.now()): void {
  try {
    localStorage.setItem(AGE_GATE_KEY, String(now + AGE_GATE_MS));
  } catch {}
}

/** True while an under-13 answer from this browser is still remembered. */
export function under13Remembered(now = Date.now()): boolean {
  try {
    const until = Number(localStorage.getItem(AGE_GATE_KEY));
    if (until > now && until - now <= AGE_GATE_MS) return true;
    localStorage.removeItem(AGE_GATE_KEY);
  } catch {}
  return false;
}
