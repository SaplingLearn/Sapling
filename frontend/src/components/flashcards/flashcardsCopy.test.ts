import { describe, expect, it } from "vitest";
import {
  HERO_PRACTICE_NOTE,
  IMPORT_PRACTICE_NOTE,
  MAP_STATUS_HINT,
  REVIEW_DONE_NOTE,
  mapStatusAria,
} from "./flashcardsCopy";

describe("W8.4 flashcards copy", () => {
  it("labels map tiers without calling them deck mastery", () => {
    expect(mapStatusAria("1 mastered, 1 struggling")).toBe("On your map: 1 mastered, 1 struggling");
    expect(MAP_STATUS_HINT).toMatch(/not from cards alone/);
  });

  it("keeps generate and review honest about retrieval vs mastery", () => {
    expect(HERO_PRACTICE_NOTE).toMatch(/Retrieval practice/i);
    expect(HERO_PRACTICE_NOTE).toMatch(/Study/);
    expect(IMPORT_PRACTICE_NOTE).toMatch(/don't set concept mastery/i);
    expect(REVIEW_DONE_NOTE).toMatch(/schedule these cards/i);
    expect(REVIEW_DONE_NOTE).toMatch(/Study/);
    expect(REVIEW_DONE_NOTE).not.toMatch(/mastered this deck/i);
  });
});
