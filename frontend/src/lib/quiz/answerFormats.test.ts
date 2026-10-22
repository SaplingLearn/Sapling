import { describe, expect, it } from "vitest";
import { expressionParts, formatNumber, numericValue, symbolicProblem } from "./answerFormats";

describe("numericValue — mirrors quiz_grading.numeric_value", () => {
  it.each([
    ["42", 42],
    ["-3.5", -3.5],
    ["−3.5", -3.5],
    [".5", 0.5],
    ["3/4", 0.75],
    ["3 / 4", 0.75],
    ["1 1/2", 1.5],
    ["-1 1/2", -1.5],
    ["1,000", 1000],
    ["1,000.5", 1000.5],
    ["75%", 0.75],
    ["3e8", 3e8],
    ["2.5E-3", 0.0025],
  ])("reads %j as %d", (raw, expected) => {
    expect(numericValue(raw)).toBeCloseTo(expected as number, 12);
  });

  it.each(["", "abc", "1,5", "1/0", "2x", "3×10^8", "1..2", "10 units"])("refuses %j", raw => {
    expect(numericValue(raw)).toBeNull();
  });

  it("formats without float noise", () => {
    expect(formatNumber(0.1 + 0.2)).toBe("0.3");
    expect(formatNumber(1 / 3)).toBe("0.3333333333");
  });
});

describe("symbolicProblem", () => {
  it.each([
    ["y = 2x", /not an equation/],
    ["sin(x)", /Functions/],
    ["2sqrt(x)", /Functions/],
    ["2(x + 1", /isn't closed/],
    ["x + 1)", /without a matching/],
  ])("flags %j", (raw, message) => {
    expect(symbolicProblem(raw)).toMatch(message);
  });

  it.each(["", "2(x + 1)", "x^2 - 1", "mgh", "ab/c"])("passes %j", raw => {
    expect(symbolicProblem(raw)).toBeNull();
  });
});

describe("expressionParts", () => {
  it("raises exponents and prettifies operators", () => {
    expect(expressionParts("2x^2 - 3*y^(n+1)")).toEqual([
      { text: "2x", sup: false },
      { text: "2", sup: true },
      { text: " − 3·y", sup: false },
      { text: "n+1", sup: true },
    ]);
  });

  it("raises a negative or single-letter exponent", () => {
    expect(expressionParts("x^-1 + a^n")).toEqual([
      { text: "x", sup: false },
      { text: "−1", sup: true },
      { text: " + a", sup: false },
      { text: "n", sup: true },
    ]);
  });

  it("leaves a dangling caret as typed", () => {
    expect(expressionParts("x^")).toEqual([{ text: "x^", sup: false }]);
  });
});
