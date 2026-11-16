import { describe, it, expect } from "vitest";
import type { GradedAssignment } from "@/lib/types";
import {
  clampEarned,
  dueSuffix,
  formatDueDisplay,
  fractionToPercentText,
  hasStoredTotal,
  parseCurvePercent,
  parseFinite,
  resolveCurveStat,
  resolveSliderRow,
  type HypotheticalScore,
} from "./predictorRow";

function a(over: Partial<GradedAssignment> = {}): GradedAssignment {
  return {
    id: "a1",
    title: "T",
    course_id: "c1",
    category_id: null,
    points_possible: 40,
    points_earned: null,
    due_date: null,
    assignment_type: null,
    notes: null,
    source: "manual",
    curve_class_mean: null,
    curve_class_sd: null,
    curve_avg_target: null,
    curve_sd_delta: null,
    ...over,
  };
}

const hyp = (over: Partial<HypotheticalScore> = {}): HypotheticalScore => ({
  earned: 5,
  possible: 10,
  curveClassMean: null,
  curveClassSd: null,
  ...over,
});

describe("hasStoredTotal", () => {
  it.each([
    [40, true],
    [0.5, true],
    [0, false],
    [-1, false],
    [null, false],
  ])("points_possible %s → %s", (pp, want) => {
    expect(hasStoredTotal(a({ points_possible: pp }))).toBe(want);
  });
});

describe("resolveCurveStat", () => {
  it("override wins, including an explicit null and 0", () => {
    expect(resolveCurveStat(0.5, 0.7)).toBe(0.5);
    expect(resolveCurveStat(null, 0.7)).toBeNull();
    expect(resolveCurveStat(0, 0.7)).toBe(0);
  });
  it("undefined override falls back to the stored stat, null when absent", () => {
    expect(resolveCurveStat(undefined, 0.7)).toBe(0.7);
    expect(resolveCurveStat(undefined, 0)).toBe(0);
    expect(resolveCurveStat(undefined, null)).toBeNull();
    expect(resolveCurveStat(undefined, undefined)).toBeNull();
  });
});

describe("resolveSliderRow", () => {
  it("stored total, no hyp: half (rounded) default earned", () => {
    expect(resolveSliderRow(a({ points_possible: 15 }), null)).toEqual({
      hasSetTotal: true,
      hasTotal: true,
      possible: 15,
      earned: 8,
      sliderMax: 15,
      curveClassMean: null,
      curveClassSd: null,
    });
  });

  it("no stored total, no hyp: 100 / 50, no total", () => {
    const r = resolveSliderRow(a({ points_possible: null }), null);
    expect(r).toMatchObject({ hasSetTotal: false, hasTotal: false, possible: 100, earned: 50, sliderMax: 100 });
  });

  it("hyp possible/earned of 0 are kept (?? not ||), slider max falls back, hasTotal false", () => {
    const r = resolveSliderRow(a({ points_possible: null }), hyp({ earned: 0, possible: 0 }));
    expect(r).toMatchObject({ hasTotal: false, possible: 0, earned: 0, sliderMax: 100 });
  });

  it("negative hyp possible: slider max 100, hasTotal true (truthy)", () => {
    const r = resolveSliderRow(a({ points_possible: null }), hyp({ possible: -3, earned: 1 }));
    expect(r).toMatchObject({ hasTotal: true, possible: -3, sliderMax: 100 });
  });

  it("hyp possible overrides a stored total; hasSetTotal stays true", () => {
    const r = resolveSliderRow(a({ points_possible: 40 }), hyp({ possible: 12.5, earned: 3 }));
    expect(r).toMatchObject({ hasSetTotal: true, hasTotal: true, possible: 12.5, earned: 3, sliderMax: 12.5 });
  });

  it("curve stats: overrides beat stored, explicit null suppresses", () => {
    const asg = a({ curve_class_mean: 0.7, curve_class_sd: 0.1 });
    expect(resolveSliderRow(asg, null)).toMatchObject({ curveClassMean: 0.7, curveClassSd: 0.1 });
    expect(resolveSliderRow(asg, hyp({ curveClassMean: 0.6, curveClassSd: null }))).toMatchObject({
      curveClassMean: 0.6,
      curveClassSd: null,
    });
  });

  it("a hyp missing the curve keys at runtime falls back to stored", () => {
    const partial = { earned: 1, possible: 2 } as unknown as HypotheticalScore;
    expect(resolveSliderRow(a({ curve_class_mean: 0.7 }), partial)).toMatchObject({ curveClassMean: 0.7, curveClassSd: null });
  });
});

describe("parseFinite", () => {
  it.each([
    ["12", 12],
    ["3.25", 3.25],
    ["-4", -4],
    ["0", 0],
    ["", 0],
    ["  ", 0],
    ["abc", null],
    ["NaN", null],
    ["Infinity", null],
  ])("%j → %s", (s, want) => {
    expect(parseFinite(s)).toBe(want);
  });
});

describe("clampEarned", () => {
  it.each([
    [5, 10, 5],
    [15, 10, 10],
    [-2, 10, 0],
    [0, 10, 0],
    [2.5, 10, 2.5],
    [9, 0, 0],
    [3, -5, 0],
  ])("clampEarned(%s, %s) → %s", (val, possible, want) => {
    expect(clampEarned(val, possible)).toBe(want);
  });
});

describe("formatDueDisplay / dueSuffix", () => {
  it("formats an ISO date as MM/DD/YYYY", () => {
    expect(formatDueDisplay("2026-03-07")).toBe("Due 03/07/2026");
    expect(formatDueDisplay("2026-12-31T23:59:00Z")).toBe("Due 12/31/2026");
    expect(dueSuffix("2026-03-07")).toBe(" · Due 03/07/2026");
  });
  it("null / empty", () => {
    expect(formatDueDisplay(null)).toBe("No Due Date");
    expect(formatDueDisplay("")).toBe("No Due Date");
    expect(dueSuffix(null)).toBe("");
    expect(dueSuffix("")).toBe("");
  });
});

describe("fractionToPercentText", () => {
  it.each([
    [0.756, "—", "76"],
    [0.825, "", "83"],
    [0, "—", "0"],
    [1.234, "", "123"],
    [-0.05, "", "-5"],
    [null, "—", "—"],
    [undefined, "", ""],
  ])("%s (fallback %j) → %j", (v, fallback, want) => {
    expect(fractionToPercentText(v, fallback)).toBe(want);
  });
});

describe("parseCurvePercent", () => {
  it.each([
    ["", null],
    ["65", 0.65],
    ["8.5", 0.085],
    ["0", 0],
    ["-10", -0.1],
    [" ", 0],
    ["abc", undefined],
  ])("%j → %s", (s, want) => {
    expect(parseCurvePercent(s)).toBe(want);
  });
});
