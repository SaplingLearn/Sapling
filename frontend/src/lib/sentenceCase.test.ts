import { describe, expect, it } from "vitest";
import { sentenceCase } from "./sentenceCase";

describe("sentenceCase", () => {
  it("capitalises only the first letter", () => {
    expect(sentenceCase("lecture notes")).toBe("Lecture notes");
    expect(sentenceCase("common")).toBe("Common");
  });
  it("leaves already-cased text alone", () => {
    expect(sentenceCase("CS 112")).toBe("CS 112");
  });
  it("renders empty values as an empty string", () => {
    expect(sentenceCase("")).toBe("");
    expect(sentenceCase(null)).toBe("");
    expect(sentenceCase(undefined)).toBe("");
  });
});
