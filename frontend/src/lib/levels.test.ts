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

import { applySkill, carriesSkill, graphUsesSkill, nodeStateWord, tierWord } from "./levels";
import { apiToGraphNode } from "./data";

describe("the graph on the ladder (the loop on)", () => {
  const graph = () => ({
    nodes: [
      { id: "a", course_id: "c1", mastery_score: 0.5, mastery_tier: "learning", skill: 0.85, skill_mastered: false },
      { id: "b", course_id: "c1", mastery_score: 0.9, mastery_tier: "mastered", skill: null, skill_mastered: false },
      { id: "c", course_id: "c1", mastery_score: 0.2, mastery_tier: "struggling", skill: 0.31, skill_mastered: false },
      { id: "subject_root__c1", course_id: "c1", mastery_score: 0.53, mastery_tier: "subject_root", is_subject_root: true },
    ],
    stats: { mastered: 1, learning: 1, struggling: 1, unexplored: 0, streak: 4 },
  });

  it("a concept's score and tier become its skill's; the map's stay beside them", () => {
    const g = applySkill(graph());
    const [a, b, c, root] = g.nodes as Array<Record<string, unknown> & { mastery_score: number }>;
    expect([a.mastery_score, a.mastery_tier, a.map_mastery_score, a.map_mastery_tier]).toEqual([0.85, "mastered", 0.5, "learning"]);
    // not started: no graded answer, never the map's 90%
    expect([b.mastery_score, b.mastery_tier]).toEqual([0, "unexplored"]);
    expect(c.mastery_tier).toBe("learning");
    expect(root.mastery_score).toBeCloseTo((0.85 + 0 + 0.31) / 3);
    expect(g.stats).toEqual({ mastered: 1, learning: 1, struggling: 0, unexplored: 1, streak: 4, skill: true });
  });

  it("a graph with no skill (the loop off) is returned exactly as it came", () => {
    const off = { nodes: [{ id: "a", mastery_score: 0.5, mastery_tier: "learning" }], stats: { mastered: 0 } };
    const before = JSON.stringify(off);
    expect(applySkill(off)).toBe(off);
    expect(JSON.stringify(off)).toBe(before);
    expect(graphUsesSkill(off.nodes)).toBe(false);
  });

  it("names a tier in the ladder's words on a skill graph, the map's otherwise", () => {
    expect(["mastered", "learning", "struggling", "unexplored"].map((t) => tierWord(t as never, true)))
      .toEqual(["Proficient", "Developing", "Getting started", "Not started"]);
    expect(tierWord("mastered", false)).toBe("Mastered");
    expect(nodeStateWord({ mastery_tier: "struggling", skill: 0.2 } as never)).toBe("getting started");
    expect(nodeStateWord({ mastery_tier: "struggling" })).toBe("struggling");
  });

  it("the adapter keeps the skill key only where the graph has one", () => {
    const course = [{ course_id: "c1", course_name: "CS", course_code: "CS1", color: "#123456" }] as never;
    const on = apiToGraphNode({ id: "a", concept_name: "A", subject: "CS", mastery_score: 0.85, mastery_tier: "mastered", skill: 0.85, skill_mastered: true } as never, course);
    const off = apiToGraphNode({ id: "a", concept_name: "A", subject: "CS", mastery_score: 0.5, mastery_tier: "learning" } as never, course);
    expect([on.skill, on.skill_mastered, carriesSkill(on)]).toEqual([0.85, true, true]);
    expect(carriesSkill(off)).toBe(false);
  });
});
