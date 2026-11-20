import { describe, expect, it } from "vitest";
import { mergeSessions, shortWhen, whenGroup } from "./sessions";

const now = new Date(2026, 10, 15, 12, 0, 0);
const at = (daysAgo: number) => new Date(2026, 10, 15 - daysAgo, 9, 0, 0).toISOString();

describe("whenGroup / shortWhen", () => {
  it("groups by calendar day, the way the sidebar's recents read", () => {
    expect(whenGroup(at(0), now)).toBe("Today");
    expect(whenGroup(at(1), now)).toBe("Yesterday");
    expect(whenGroup(at(3), now)).toBe("Previous 7 days");
    expect(whenGroup(at(9), now)).toBe("Older");
    expect(whenGroup("not a date", now)).toBe("Older");
    expect(shortWhen(at(0), now)).toBe("today");
    expect(shortWhen(at(1), now)).toBe("yesterday");
  });
});

describe("mergeSessions", () => {
  const recent = [
    { id: "a", topic: "Recursion", mode: "socratic", course_id: "c1", started_at: at(0), ended_at: null, message_count: 3, is_active: true, loop_open: true },
    { id: "b", topic: "Quadratics", mode: "socratic", course_id: "c2", started_at: at(1), ended_at: null, message_count: 2, is_active: true, loop_open: true },
    { id: "c", topic: "Big-O", mode: "socratic", course_id: "c1", started_at: at(2), ended_at: null, message_count: 4, is_active: true, loop_open: false },
  ];

  it("marks a session open from the loop, never from is_active alone", () => {
    const rows = mergeSessions(recent, null, null);
    expect(rows.map((r) => [r.id, r.open])).toEqual([["a", true], ["b", true], ["c", false]]);
  });

  it("the course on screen: its open list is authoritative and lists a session just started", () => {
    const rows = mergeSessions(recent, [{ session_id: "new", topic: "", started_at: at(0), phase: "probe" }], "c1");
    const byId = Object.fromEntries(rows.map((r) => [r.id, r]));
    expect(byId.new).toMatchObject({ courseId: "c1", open: true });
    expect(byId.a.open).toBe(false); // closed since the recents were read
    expect(byId.b.open).toBe(true); // another course: left as listed
    expect(rows[rows.length - 1].id).toBe("c"); // newest first
  });
});

describe("mergeSessions — a capped open list (#866 K29)", () => {
  const row = (id: string, daysAgo: number, loopOpen: boolean) => (
    { id, topic: id, mode: "socratic", course_id: "c1", started_at: at(daysAgo), ended_at: null, message_count: 1, is_active: true, loop_open: loopOpen }
  );
  const listedOpen = (id: string, daysAgo: number) => ({ session_id: id, topic: id, started_at: at(daysAgo), phase: "teach" as const });

  it("an open session older than an incomplete list's oldest stays open", () => {
    const rows = mergeSessions([row("new", 0, true), row("old", 9, true)], [listedOpen("new", 0)], "c1", false);
    expect(Object.fromEntries(rows.map((r) => [r.id, r.open]))).toEqual({ new: true, old: true });
  });

  it("an unlisted session newer than the list's oldest was wrapped up since the recents were read", () => {
    const rows = mergeSessions([row("mid", 2, true), row("new", 0, true)], [listedOpen("new", 0), listedOpen("older", 5)], "c1", false);
    expect(rows.find((r) => r.id === "mid")?.open).toBe(false);
  });

  it("a complete list decides every row of its course", () => {
    const rows = mergeSessions([row("old", 9, true)], [listedOpen("new", 0)], "c1", true);
    expect(rows.find((r) => r.id === "old")?.open).toBe(false);
  });
});
