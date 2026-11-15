import { describe, expect, it } from "vitest";
import { isWrittenAnswerFormatValid, numericValue } from "./answerFormats";

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
});

describe("isWrittenAnswerFormatValid", () => {
  it.each(["", "y = 2x", "sin(x)", "2(x + 1", "x + 1)", "x^", "x^9", "x**2", "x/", "()", "x$"])(
    "blocks malformed algebra %j",
    raw => expect(isWrittenAnswerFormatValid("symbolic", raw)).toBe(false),
  );

  it.each(["2(x + 1)", "x^2 - 1", "mgh", "ab/c", "x^-2", "a × b"])(
    "accepts algebra %j",
    raw => expect(isWrittenAnswerFormatValid("symbolic", raw)).toBe(true),
  );

  it("requires a number and a unit symbol when the question asks for units", () => {
    expect(isWrittenAnswerFormatValid("numeric", "250 cm", "m")).toBe(true);
    expect(isWrittenAnswerFormatValid("numeric", "250", "m")).toBe(false);
    expect(isWrittenAnswerFormatValid("numeric", "cm", "m")).toBe(false);
  });
});
