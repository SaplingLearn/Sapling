import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { BAND_DEVELOP_MAX, BAND_NOVICE_MAX, LEVEL_TONE, LEVEL_WORDS, bandFor, levelFor, levelPhrase } from "./levels";
import { MASTERY_PALETTE } from "./graph/nodeStyle";
import { BAND_WORDS } from "./quiz/proposals";

describe("the one skill ladder", () => {
  it("cuts where the backend does (backend/learning/params.py)", () => {
    const params = readFileSync(join(__dirname, "../../../backend/learning/params.py"), "utf8");
    expect(params).toMatch(new RegExp(`^BAND_NOVICE_MAX = ${BAND_NOVICE_MAX.toFixed(2)}$`, "m"));
    expect(params).toMatch(new RegExp(`^BAND_DEVELOP_MAX = ${BAND_DEVELOP_MAX.toFixed(2)}$`, "m"));
  });

  it.each([
    [0, "novice"], [0.29, "novice"], [0.3, "develop"], [0.79, "develop"], [0.8, "profic"], [1, "profic"],
  ] as const)("a belief of %s is %s", (p, band) => {
    expect(bandFor(p)).toBe(band);
    expect(levelFor(p)).toBe(band);
  });

  it("no belief is Not started, never Getting started", () => {
    expect(levelFor(null)).toBe("not_started");
    expect(levelFor(undefined)).toBe("not_started");
    expect(levelFor(Number.NaN)).toBe("not_started");
  });

  it("has four words, none of them Mastered (a badge, not a level)", () => {
    expect(Object.values(LEVEL_WORDS)).toEqual(["Not started", "Getting started", "Developing", "Proficient"]);
    expect(Object.values(LEVEL_WORDS)).not.toContain("Mastered");
    expect(levelPhrase("develop")).toBe("developing");
  });

  it("the quiz says the same words mid-sentence", () => {
    expect(BAND_WORDS).toEqual({ novice: "getting started", develop: "developing", profic: "proficient" });
  });

  it("colours low to high from the app's mastery palette", () => {
    expect(LEVEL_TONE.profic).toBe(MASTERY_PALETTE.mastered);
    expect(LEVEL_TONE.not_started).toBe(MASTERY_PALETTE.unexplored);
  });
});
