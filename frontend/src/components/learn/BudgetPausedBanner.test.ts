import { describe, expect, it } from "vitest";
import { formatResetAt, tutorPauseMessage } from "./BudgetPausedBanner";

/** The month and day `at` falls on in the runner's zone, as the banner prints them. */
const monthDay = (at: string) => new Date(at).toLocaleString(undefined, { month: "short", day: "numeric" });
const weekday = (at: string) => new Date(at).toLocaleString(undefined, { weekday: "short" });

describe("formatResetAt (#866 K18)", () => {
  const now = new Date(2026, 10, 18, 9, 0); // Wed Nov 18, 09:00 local

  it("a reset later today is its time alone", () => {
    const at = new Date(2026, 10, 18, 19, 0).toISOString();
    const text = formatResetAt(at, now);
    expect(text).not.toContain(weekday(at));
    expect(text).not.toContain(monthDay(at));
  });

  it("a reset within the week names its weekday", () => {
    const at = new Date(2026, 10, 20, 19, 0).toISOString();
    expect(formatResetAt(at, now)).toContain(weekday(at));
    expect(formatResetAt(at, now)).not.toContain(monthDay(at));
  });

  it("a reset a week or more away names its date, never a bare weekday", () => {
    // the monthly cap lifts on the 1st: from Nov 18 that is 13 days away, and
    // "Mon 7:00 PM" would read as next Monday
    const at = new Date(2026, 11, 1, 0, 0).toISOString();
    expect(formatResetAt(at, now)).toContain(monthDay(at));
    const week = new Date(2026, 10, 25, 9, 0).toISOString();
    expect(formatResetAt(week, now)).toContain(monthDay(week));
  });

  it("an unreadable time reads as later", () => {
    expect(formatResetAt("not a date", now)).toBe("later");
  });
});

describe("tutorPauseMessage (#866 K35)", () => {
  it("at a hard level that holds novice checks, says so instead of 'practice keeps working'", () => {
    const text = tutorPauseMessage(null, false, true);
    expect(text).toContain("checks on concepts you're just starting are paused too");
    expect(text).not.toContain("Practice and review keep working");
    expect(tutorPauseMessage(null, true, true)).toContain("for this session");
  });

  it("a rate-limit-only pause holds no check: practice and review keep working", () => {
    expect(tutorPauseMessage(null, false)).toBe("Tutor chat paused for now. Practice and review keep working.");
    expect(tutorPauseMessage(null, false, false)).toContain("Practice and review keep working");
  });
});
