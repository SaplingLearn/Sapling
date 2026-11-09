import { describe, expect, it } from "vitest";
import {
  asciiExpression,
  asciiNumber,
  expressionParts,
  formatNumber,
  numericValue,
  prettyExpression,
  prettyNumber,
  superscriptParts,
  symbolicProblem,
} from "./answerFormats";

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

describe("superscriptParts — a stem's exponents, and nothing else", () => {
  it("raises exponents but leaves hyphens and asterisks alone", () => {
    expect(superscriptParts("Expand (x + 1)^2 - 2x for a well-known *case*")).toEqual([
      { text: "Expand (x + 1)", sup: false },
      { text: "2", sup: true },
      { text: " - 2x for a well-known *case*", sup: false },
    ]);
  });

  it("returns prose without a caret as one part", () => {
    expect(superscriptParts("What is a base case?")).toEqual([{ text: "What is a base case?", sup: false }]);
  });
});

describe("prettyExpression / asciiExpression — the algebra field typeset in place", () => {
  it.each([
    ["x^2 + 1", "x² + 1"],
    ["2(x+1)^2 - 3*x", "2(x+1)² − 3·x"],
    ["x^-1", "x⁻¹"],
    ["2^10", "2¹⁰"],
  ])("shows %j as %j, and reads it back exactly", (ascii, shown) => {
    expect(prettyExpression(ascii)).toBe(shown);
    expect(asciiExpression(shown)).toBe(ascii);
  });

  it.each([
    ["x^", "x^"],          // an exponent still being typed
    ["x^-", "x^−"],
    ["x^q", "x^q"],        // no superscript q
    ["x^(2*y)", "x^(2·y)"], // no superscript ·
    ["x^(n+1)", "x^(n+1)"], // letters and brackets stay as typed
    ["e^x", "e^x"],
    ["x^(2)", "x^(2)"],
    ["x^1.5", "x^1.5"],     // no superscript point
    ["x^2^3", "x²^3"],      // a stacked power: two runs would read back as one
    ["x^(n+1)^2", "x^(n+1)²"], // the bracketed power isn't raised, so the ² can be
  ])("leaves %j raised only where it can be (%j)", (ascii, shown) => {
    expect(prettyExpression(ascii)).toBe(shown);
    expect(asciiExpression(shown)).toBe(ascii);
  });

  it("reads a digit typed after an exponent the way the grader will: as more exponent", () => {
    expect(asciiExpression("x²3")).toBe("x^23");
    expect(prettyExpression("x^23")).toBe("x²³");
  });

  it("still reads a pasted letter or bracket superscript back to ASCII", () => {
    expect(asciiExpression("x⁽ⁿ⁺¹⁾")).toBe("x^(n+1)");
  });

  it("never lets a typeset character through to the grader", () => {
    expect(asciiExpression("x² × 3 ÷ y − 1")).toBe("x^2 * 3 / y - 1");
  });
});

describe("prettyNumber / asciiNumber — the numeric field typeset in place", () => {
  it.each([
    ["3e8", "3×10⁸"],
    ["1.5e-3", "1.5×10⁻³"],
    ["-2.5", "−2.5"],
    ["6.02e23", "6.02×10²³"],
    ["3/4", "3/4"],   // the value is never rewritten, only the notation
    ["75%", "75%"],
    ["1,000", "1,000"],
  ])("shows %j as %j, and reads it back exactly", (ascii, shown) => {
    expect(prettyNumber(ascii)).toBe(shown);
    expect(asciiNumber(shown)).toBe(ascii);
  });

  it("reads a capital E the same way (the grader takes either)", () => {
    expect(prettyNumber("1.5E-3")).toBe("1.5×10⁻³");
  });

  it("leaves an exponent that is still being typed alone", () => {
    expect(prettyNumber("3e")).toBe("3e");
    expect(prettyNumber("3e-")).toBe("3e−");
    expect(asciiNumber("3e−")).toBe("3e-");
  });

  it("hands the grader a number it can read", () => {
    expect(numericValue(asciiNumber("3×10⁸"))).toBe(3e8);
    expect(numericValue(asciiNumber("−1.5×10⁻³"))).toBeCloseTo(-0.0015);
  });
});
