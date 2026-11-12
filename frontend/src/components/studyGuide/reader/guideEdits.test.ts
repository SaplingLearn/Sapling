/**
 * The changes a stream, a regenerated block or an answer makes to the guide
 * the reader holds.
 */
import { describe, expect, it } from "vitest";

import type { AnswerResult, Block, CheckBlock, GuideContent, Section } from "@/lib/studyGuide/types";

import { applyOutline, applySection, recordAnswer, replaceBlock, toggleRead } from "./guideEdits";
import { fixtureGuide as guide } from "./readerFixture";

/** The fixture's outline with only the named sections kept as written. */
function outlineKeeping(...kept: string[]): GuideContent {
  const { content } = guide();
  return {
    ...content,
    sections: content.sections.map(section =>
      kept.includes(section.id) ? { ...section, status: "written" } : { ...section, status: "queued", items: [] },
    ),
  };
}

const ANSWERED = { "s1-i8": { option_id: "b", correct: true } };

describe("the outline arriving", () => {
  it("replaces the content and the title", () => {
    const content = { ...guide().content, title: "A new title", sections: [] };
    const next = applyOutline(guide(), content);
    expect(next.title).toBe("A new title");
    expect(next.content).toBe(content);
  });

  it("drops every read mark and answer when the whole guide is rewritten", () => {
    // A regenerated guide numbers its sections s1.. again: the old marks
    // would land on the new sections.
    const before = guide({ read_sections: ["s1", "s2"], answers: ANSWERED });
    const next = applyOutline(before, outlineKeeping());
    expect(next.read_sections).toEqual([]);
    expect(next.answers).toEqual({});
  });

  it("keeps the marks and answers of the sections an update keeps", () => {
    const before = guide({ read_sections: ["s1", "s2", "s4"], answers: { ...ANSWERED, "s2-i9": { option_id: "a", correct: false } } });
    const next = applyOutline(before, outlineKeeping("s1", "s4"));
    expect(next.read_sections).toEqual(["s1", "s4"]);
    expect(next.answers).toEqual(ANSWERED);
  });
});

describe("edits to the guide", () => {
  it("puts a written section where its queued one was", () => {
    const written: Section = { ...guide().content.sections[2], status: "written", one_line: "Now written." };
    const next = applySection(guide(), written);
    expect(next.content.sections.map(s => s.status)).toEqual(["written", "written", "written", "written"]);
    expect(next.content.sections[2].one_line).toBe("Now written.");
  });

  it("replaces one block and leaves every other item alone", () => {
    const before = guide();
    const block: Block = { type: "key_terms", id: "s2-i2", title: "Rewritten", terms: [] };
    const next = replaceBlock(before, "s2-i2", block);
    expect(next.content.sections[1].items[1]).toBe(block);
    expect(next.content.sections[1].items[0]).toEqual(before.content.sections[1].items[0]);
    expect(next.content.sections[0]).toEqual(before.content.sections[0]);
  });

  it("toggles a read mark", () => {
    expect(toggleRead(["s2"], "s1")).toEqual(["s2", "s1"]);
    expect(toggleRead(["s2", "s1"], "s2")).toEqual(["s1"]);
  });
});

describe("an answer", () => {
  const result = (over: Partial<AnswerResult> = {}): AnswerResult => ({
    correct: true,
    correct_id: "b",
    explanation: "0, 2, 4 and 6 pass the test.",
    counted: true,
    mastery: null,
    ...over,
  });
  const check = (g: ReturnType<typeof guide>) =>
    g.content.sections[0].items.find(item => item.id === "s1-i8") as CheckBlock;

  it("is recorded, and moves mastery only when the server says it did", () => {
    const moved = recordAnswer(guide(), "s1-i8", "b", result({ mastery: { concept: "Loops", before: "struggling", after: "learning" } }));
    expect(moved.answers["s1-i8"]).toEqual({ option_id: "b", correct: true });
    expect(moved.mastery.Loops).toBe("learning");
    expect(recordAnswer(guide(), "s1-i8", "b", result()).mastery).toEqual(guide().mastery);
  });

  it("leaves the question as the server would send it next: the answer and this pick's explanation", () => {
    const right = check(recordAnswer(guide(), "s1-i8", "b", result()));
    expect(right.correct_id).toBe("b");
    expect(right.explain_correct).toBe("0, 2, 4 and 6 pass the test.");
    expect(right.explain_incorrect).toBeNull();

    const wrong = check(recordAnswer(guide(), "s1-i8", "a", result({ correct: false, explanation: "Count the passes." })));
    expect(wrong.explain_incorrect).toBe("Count the passes.");
    expect(wrong.explain_correct).toBeNull();
  });
});
