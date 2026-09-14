import { describe, expect, it } from "vitest";
import { daysAgo, relativeStudied } from "./relativeTime";

// Local-midnight arithmetic, so the fixtures are built in local time too.
function at(year: number, month: number, day: number, hour = 12): Date {
  return new Date(year, month - 1, day, hour);
}

const NOW = at(2026, 8, 22, 9);

describe("daysAgo", () => {
  it("counts calendar days, not 24-hour blocks", () => {
    // 11pm the previous evening is ten hours ago, but it is yesterday.
    expect(daysAgo(at(2026, 8, 21, 23).toISOString(), NOW)).toBe(1);
    expect(daysAgo(at(2026, 8, 22, 1).toISOString(), NOW)).toBe(0);
    expect(daysAgo(at(2026, 8, 18, 8).toISOString(), NOW)).toBe(4);
  });

  it("clamps a future timestamp to today", () => {
    expect(daysAgo(at(2026, 8, 25).toISOString(), NOW)).toBe(0);
  });

  it("returns null for absent or unparseable input", () => {
    expect(daysAgo(null, NOW)).toBeNull();
    expect(daysAgo(undefined, NOW)).toBeNull();
    expect(daysAgo("", NOW)).toBeNull();
    expect(daysAgo("not a date", NOW)).toBeNull();
  });
});

describe("relativeStudied", () => {
  it("names today and yesterday", () => {
    expect(relativeStudied(at(2026, 8, 22, 1).toISOString(), NOW)).toBe("today");
    expect(relativeStudied(at(2026, 8, 21, 23).toISOString(), NOW)).toBe("yesterday");
  });

  it("counts days beyond that", () => {
    expect(relativeStudied(at(2026, 8, 18).toISOString(), NOW)).toBe("4 days ago");
    expect(relativeStudied(at(2026, 8, 13).toISOString(), NOW)).toBe("9 days ago");
  });

  it("says so when a concept was never studied", () => {
    expect(relativeStudied(null, NOW)).toBe("not studied yet");
  });
});
