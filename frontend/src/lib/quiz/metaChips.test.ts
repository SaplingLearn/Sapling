import { describe, it, expect } from "vitest";
import {
  examDistanceFilled,
  examDistancePips,
  isReturningConcept,
} from "./metaChips";

describe("isReturningConcept", () => {
  it("is on after any prior study", () => {
    expect(isReturningConcept(0, null)).toBe(false);
    expect(isReturningConcept(1, null)).toBe(true);
    expect(isReturningConcept(0, "2026-11-01T00:00:00Z")).toBe(true);
  });
});

describe("examDistancePips", () => {
  it("maps tier (+ learning score split) to 1…5", () => {
    expect(examDistancePips("mastered", 0.9)).toBe(1);
    expect(examDistancePips("learning", 0.6)).toBe(2);
    expect(examDistancePips("learning", 0.4)).toBe(3);
    expect(examDistancePips("struggling", 0.2)).toBe(4);
    expect(examDistancePips("unexplored", 0)).toBe(5);
  });

  it("fills more pips when nearer exam-ready", () => {
    expect(examDistanceFilled(1)).toBe(5);
    expect(examDistanceFilled(5)).toBe(1);
  });
});
