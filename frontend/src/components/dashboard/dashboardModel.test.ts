import { describe, it, expect } from "vitest";
import type { GraphNode } from "@/lib/data";
import { activeDaysFrom, assignmentUrgency, statsFromGraph, streakMarkState } from "./dashboardModel";

describe("statsFromGraph", () => {
  it("maps the wire counters, total_nodes → total", () => {
    expect(statsFromGraph({ streak: 3, mastered: 4, total_nodes: 9, learning: 2, struggling: 1, unexplored: 2 }))
      .toEqual({ streak: 3, mastered: 4, total: 9, learning: 2, struggling: 1, unexplored: 2 });
  });

  it("zeroes a missing block or a missing counter", () => {
    const zero = { streak: 0, mastered: 0, total: 0, learning: 0, struggling: 0, unexplored: 0 };
    expect(statsFromGraph(undefined)).toEqual(zero);
    expect(statsFromGraph(null)).toEqual(zero);
    expect(statsFromGraph({ mastered: 2 })).toEqual({ ...zero, mastered: 2 });
  });
});

describe("activeDaysFrom", () => {
  const node = (last?: string): GraphNode => ({
    id: "n", name: "N", subject: "S", color: "#000", mastery_tier: "learning", mastery_score: 0.5, course_id: "c", last_studied_at: last,
  });

  it("collects the UTC dates of the parseable last-studied timestamps", () => {
    const days = activeDaysFrom([
      node("2026-03-02T10:00:00Z"),
      node("2026-03-02T23:00:00Z"),
      node("2026-03-04T01:00:00Z"),
      node(undefined),
      node("garbage"),
    ]);
    expect([...days]).toEqual(["2026-03-02", "2026-03-04"]);
  });
});

describe("assignmentUrgency", () => {
  const NOW = Date.UTC(2026, 2, 4, 12);
  const due = (h: number) => new Date(NOW + h * 3600_000).toISOString();

  it.each([
    [-1, "chip--err", "OVERDUE"],
    [0, "chip--err", "OVERDUE"],
    [0.5, "chip--err", "NOW"],
    [1, "chip--err", "1H"],
    [5.4, "chip--err", "5H"],
    [24, "chip--err", "24H"],
    [25, "chip--warn", "2D"],
    [48, "chip--warn", "2D"],
    [49, "chip--info", "3D"],
    [100, "chip--info", "5D"],
  ])("due in %sh → %s %s", (h, chipClass, label) => {
    expect(assignmentUrgency(due(h as number), NOW)).toEqual({ chipClass, label });
  });
});

describe("streakMarkState", () => {
  const today = new Date(2026, 2, 4);
  const day = (n: number) => new Date(2026, 2, n);

  it("done wins over today; otherwise today, past = missed, ahead = future", () => {
    const active = new Set([day(4).toISOString().slice(0, 10), day(2).toISOString().slice(0, 10)]);
    expect(streakMarkState(day(4), today, active)).toBe("done");
    expect(streakMarkState(day(2), today, active)).toBe("done");
    expect(streakMarkState(day(4), today, new Set())).toBe("today");
    expect(streakMarkState(day(3), today, active)).toBe("missed");
    expect(streakMarkState(day(5), today, active)).toBe("future");
  });
});
