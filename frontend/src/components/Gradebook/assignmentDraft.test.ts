import { afterEach, beforeEach, describe, it, expect, vi } from "vitest";

import {
  CLEARED_CURVE,
  draftFromAssignment,
  emptyDraft,
  formatPercent,
  hasCurveStats,
  isDraftValid,
  isDueDateInvalid,
  parsePercent,
  parsePoints,
} from "./assignmentDraft";
import type { GradedAssignment } from "@/lib/types";

const EMPTY = {
  title: "",
  category_id: null,
  points_possible: null,
  points_earned: null,
  due_date: null,
  assignment_type: null,
  notes: null,
  curve_class_mean: null,
  curve_class_sd: null,
  curve_avg_target: null,
  curve_sd_delta: null,
};

const ASSIGNMENT: GradedAssignment = {
  id: "a1",
  title: "Midterm",
  course_id: "course-1",
  category_id: "c1",
  points_possible: 100,
  points_earned: 88,
  due_date: "2026-03-14",
  assignment_type: "exam",
  notes: "open book",
  source: "gradescope",
  curve_class_mean: 0.68,
  curve_class_sd: 0.12,
  curve_avg_target: 0.8,
  curve_sd_delta: 0.1,
};

describe("emptyDraft / draftFromAssignment", () => {
  it("builds a fresh all-null draft with a blank title", () => {
    expect(emptyDraft()).toEqual(EMPTY);
    expect(emptyDraft()).not.toBe(emptyDraft());
  });

  it.each([undefined, null])("treats %s as create", (initial) => {
    expect(draftFromAssignment(initial)).toEqual(EMPTY);
  });

  it("copies exactly the editable fields, in draft key order", () => {
    const draft = draftFromAssignment(ASSIGNMENT);
    expect(draft).toEqual({
      title: "Midterm",
      category_id: "c1",
      points_possible: 100,
      points_earned: 88,
      due_date: "2026-03-14",
      assignment_type: "exam",
      notes: "open book",
      curve_class_mean: 0.68,
      curve_class_sd: 0.12,
      curve_avg_target: 0.8,
      curve_sd_delta: 0.1,
    });
    expect(Object.keys(draft)).toEqual(Object.keys(EMPTY));
  });

  it("keeps stored zeros and empty strings (?? not ||)", () => {
    const draft = draftFromAssignment({
      ...ASSIGNMENT,
      title: "",
      notes: "",
      points_possible: 0,
      points_earned: 0,
      curve_class_mean: 0,
      curve_sd_delta: 0,
    });
    expect(draft).toMatchObject({
      title: "",
      notes: "",
      points_possible: 0,
      points_earned: 0,
      curve_class_mean: 0,
      curve_sd_delta: 0,
    });
  });

  it("falls back to null for missing (undefined) fields from a loose payload", () => {
    const loose = { id: "a2", title: undefined } as unknown as GradedAssignment;
    expect(draftFromAssignment(loose)).toEqual(EMPTY);
  });
});

describe("parsePoints", () => {
  it.each([
    ["", null],
    ["0", 0],
    ["12.5", 12.5],
    ["-3", -3],
    ["100", 100],
  ])("%j → %s", (input, expected) => {
    expect(parsePoints(input)).toBe(expected);
  });

  it("passes non-numeric text through Number (NaN), like the old inline parse", () => {
    expect(parsePoints("abc")).toBeNaN();
  });
});

describe("parsePercent / formatPercent", () => {
  it.each([
    ["", null],
    ["0", 0],
    ["68", 0.68],
    ["12.5", 0.125],
    ["-10", -0.1],
  ])("parsePercent(%j) → %s", (input, expected) => {
    expect(parsePercent(input)).toBe(expected);
  });

  it.each([
    [null, ""],
    [0, "0.0"],
    [0.68, "68.0"],
    [0.125, "12.5"],
    [0.12345, "12.3"],
    [-0.1, "-10.0"],
  ])("formatPercent(%s) → %j", (input, expected) => {
    expect(formatPercent(input)).toBe(expected);
  });
});

describe("isDueDateInvalid", () => {
  // Parsed as LOCAL midnight and compared against the UTC ISO date, exactly
  // as before the split — the valid-date cases only hold in a UTC-or-west
  // timezone, so the zone is pinned to UTC (what CI runs) for this block.
  beforeEach(() => {
    vi.stubEnv("TZ", "UTC");
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it.each([
    [null, false],
    ["", false],
    ["2026-03-14", false],
    ["2024-02-29", false],
    ["2026-02-30", true],
    ["2025-02-29", true],
    ["2026-13-01", true],
    ["not a date", true],
  ])("%j → %s", (input, expected) => {
    expect(isDueDateInvalid(input)).toBe(expected);
  });
});

describe("isDraftValid", () => {
  const base = { ...EMPTY, title: "PS 1" };

  it("needs a non-blank title", () => {
    expect(isDraftValid(base, false)).toBe(true);
    expect(isDraftValid({ ...base, title: "" }, false)).toBe(false);
    expect(isDraftValid({ ...base, title: "  \t" }, false)).toBe(false);
  });

  it.each([
    [null, true],
    [0.01, true],
    [100, true],
    [0, false],
    [-5, false],
  ])("points_possible %s → %s", (total, expected) => {
    expect(isDraftValid({ ...base, points_possible: total }, false)).toBe(expected);
  });

  it("ignores points_earned entirely", () => {
    expect(isDraftValid({ ...base, points_earned: -50 }, false)).toBe(true);
  });

  it("fails on an invalid due date", () => {
    expect(isDraftValid(base, true)).toBe(false);
  });
});

describe("hasCurveStats / CLEARED_CURVE", () => {
  it("is true when either the class mean or SD is set (0 counts)", () => {
    expect(hasCurveStats(EMPTY)).toBe(false);
    expect(hasCurveStats({ ...EMPTY, curve_class_mean: 0 })).toBe(true);
    expect(hasCurveStats({ ...EMPTY, curve_class_sd: 0.1 })).toBe(true);
    expect(hasCurveStats({ ...EMPTY, curve_avg_target: 0.8, curve_sd_delta: 0.1 })).toBe(false);
  });

  it("clears all four curve fields and nothing else", () => {
    expect(CLEARED_CURVE).toEqual({
      curve_class_mean: null,
      curve_class_sd: null,
      curve_avg_target: null,
      curve_sd_delta: null,
    });
  });
});
