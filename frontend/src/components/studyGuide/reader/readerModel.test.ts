/**
 * The reader's pure derivations: labels, the countdown, progress, section
 * phases and the tutor question. The edits are in guideEdits.test.ts.
 */
import { describe, expect, it } from "vitest";

import type { Section } from "@/lib/studyGuide/types";

import { fixtureGuide } from "./readerFixture";
import {
  conceptTier,
  countdownLabel,
  daysLeftLabel,
  daysUntil,
  findSource,
  liveTier,
  madeFromLabel,
  progressTitle,
  readCount,
  sectionBars,
  sectionNumber,
  sectionPhases,
  sourcesLabel,
  staleLabel,
  tutorQuestion,
} from "./readerModel";

const guide = fixtureGuide;
const NOW = new Date(2026, 2, 11, 9, 0, 0);

describe("the exam countdown", () => {
  it("counts whole days to the due date", () => {
    expect(daysUntil("2026-03-17", NOW)).toBe(6);
    expect(daysUntil("2026-03-17T23:00:00+00:00", NOW)).toBe(6);
    expect(daysUntil("2026-03-11", NOW)).toBe(0);
  });

  it("is null with no date, a date that has passed, or one that is not a date", () => {
    expect(daysUntil(null, NOW)).toBeNull();
    expect(daysUntil("2026-03-10", NOW)).toBeNull();
    expect(daysUntil("soon", NOW)).toBeNull();
  });

  it("is worded for today, one day and several", () => {
    expect(countdownLabel("Midterm Exam", 0)).toBe("Midterm Exam is today");
    expect(countdownLabel("Midterm Exam", 1)).toBe("Midterm Exam in 1 day");
    expect(countdownLabel("Midterm Exam", 6)).toBe("Midterm Exam in 6 days");
    expect(daysLeftLabel(0)).toBe("Today");
    expect(daysLeftLabel(1)).toBe("1 day left");
    expect(daysLeftLabel(6)).toBe("6 days left");
  });
});

describe("labels and counts", () => {
  it("numbers sections with two digits", () => {
    expect(sectionNumber(0)).toBe("01");
    expect(sectionNumber(11)).toBe("12");
  });

  it("leaves the reading time off until the guide has one", () => {
    expect(sourcesLabel(3, 12)).toBe("3 sources · about 12 min");
    expect(sourcesLabel(1, 0)).toBe("1 source");
  });

  it("counts new lectures in the singular and the plural", () => {
    expect(staleLabel(1)).toBe("1 new lecture since this guide was made");
    expect(staleLabel(2)).toBe("2 new lectures since this guide was made");
  });

  it("reads the space bar off the sections", () => {
    expect(sectionBars(guide().content)).toEqual(guide().bars);
  });

  it("counts only read marks that belong to a section of the guide", () => {
    expect(readCount(guide())).toBe(1);
    expect(readCount({ ...guide(), read_sections: ["s2", "gone"] })).toBe(1);
  });

  it("says the guide is finished once every section is read", () => {
    expect(progressTitle(1, 4)).toBe("1 of 4 sections read");
    expect(progressTitle(4, 4)).toBe("Guide finished");
    expect(progressTitle(0, 0)).toBe("0 of 0 sections read");
  });
});

describe("mastery", () => {
  const section = (over: Partial<Section>): Section => ({ ...guide().content.sections[0], ...over });

  it("uses live mastery for a section, and its tier when written as the fallback", () => {
    expect(liveTier(section({ concept: "Loops", tier: "struggling" }), { Loops: "learning" })).toBe("learning");
    expect(liveTier(section({ concept: "Loops", tier: "struggling" }), {})).toBe("struggling");
    expect(liveTier(section({ concept: null, tier: "unexplored" }), { Loops: "mastered" })).toBe("unexplored");
  });

  it("treats a concept the tree does not have as not started", () => {
    expect(conceptTier("Loops", { Loops: "struggling" })).toBe("struggling");
    expect(conceptTier("Recursion", {})).toBe("unexplored");
  });

  it("counts the documents a guide was made from, and names the quiz history apart from them", () => {
    const { sources } = guide().content;
    expect(madeFromLabel(sources)).toBe("Made from 2 of your materials and your quiz history");
    expect(madeFromLabel(sources.slice(0, 2))).toBe("Made from 2 of your materials");
  });

  it("finds a cited source, or nothing", () => {
    const { sources } = guide().content;
    expect(findSource(sources, "quiz-history")?.name).toBe("Your quiz history");
    expect(findSource(sources, "document:missing")).toBeNull();
    expect(findSource(sources, null)).toBeNull();
  });
});

describe("section phases", () => {
  const sections = guide().content.sections;
  const withStatus = (id: string, status: "queued" | "failed") =>
    sections.map(s => (s.id === id ? { ...s, status } : s));

  it("is each section's own status when nothing is being written", () => {
    expect(sectionPhases(sections, false, [])).toEqual({ s1: "written", s2: "written", s3: "queued", s4: "written" });
    expect(sectionPhases(withStatus("s3", "failed"), false, []).s3).toBe("failed");
  });

  it("calls the first queued section the one being written", () => {
    const queued = sections.map(s => ({ ...s, status: "queued" as const }));
    expect(sectionPhases(queued, true, [])).toEqual({ s1: "writing", s2: "queued", s3: "queued", s4: "queued" });
    expect(sectionPhases(sections, true, []).s3).toBe("writing");
  });

  it("writes a section that failed before in its turn: first it is being written, later ones wait", () => {
    // s2 failed on an earlier run and s3 is still queued: the server takes s2 first.
    const cut = withStatus("s2", "failed");
    expect(sectionPhases(cut, true, [])).toEqual({ s1: "written", s2: "writing", s3: "queued", s4: "written" });
    const both = cut.map(s => (s.id === "s3" ? { ...s, status: "failed" as const } : s));
    expect(sectionPhases(both, true, [])).toMatchObject({ s2: "writing", s3: "queued" });
  });

  it("keeps a section failed once this run has tried it, and moves on", () => {
    const cut = withStatus("s2", "failed");
    expect(sectionPhases(cut, true, ["s2"])).toEqual({ s1: "written", s2: "failed", s3: "writing", s4: "written" });
  });
});

describe("the tutor question", () => {
  it("carries the guide's title, its sections and the question", () => {
    const message = tutorQuestion(guide(), "Why does a loop stop?");
    expect(message).toContain('"Control flow and functions"');
    expect(message).toContain("CS 101");
    expect(message).toContain("1. Loops: A loop repeats a block until its condition turns false.");
    expect(message).toContain("4. Variables: A variable is a name bound to a value.");
    expect(message).toContain("My question: Why does a loop stop?");
  });
});
