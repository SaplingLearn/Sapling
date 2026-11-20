/**
 * The landing page's demo course labels every concept the way the app does.
 *
 * The demo graph shows a tier label and a mastery percentage side by side
 * (ActGraph's inspector: "MASTERED 82%"). The app classifies a score with one
 * function — backend learning/bkt.py::tier_for, mirrored by
 * lib/graph/nodeStyle.ts::tierFor and pinned to learning/params.py by
 * backend/tests/test_mastery_tier_unification.py — so a demo label that
 * disagrees with it teaches a visitor the wrong cut-offs (#866 K51).
 */
import { describe, expect, it } from "vitest";

import { tierFor } from "@/lib/graph/nodeStyle";
import { COURSE, nodeUses, type GraphNode } from "./course";
import { buildGraph } from "./engine/graph";

const everyConcept: GraphNode[] = COURSE.topics.flatMap((topic) => [topic, ...topic.subs]);

describe("the landing demo course", () => {
  it.each(everyConcept.map((node) => [node.label, node] as const))(
    "%s carries the tier the app gives its score",
    (_label, node) => {
      expect(node.tier).toBe(tierFor(node.mastery));
    },
  );

  it("labels the course node by the same cuts", () => {
    const root = buildGraph().nodes[0];
    expect(root.root).toBe(true);
    expect(root.tier).toBe(tierFor(root.mastery));
  });

  it("keeps every tier on the map", () => {
    const tiers = new Set(everyConcept.map((node) => node.tier));
    expect(tiers).toEqual(new Set(["mastered", "learning", "struggling", "unexplored"]));
  });
});

describe("nodeUses", () => {
  const mastered = everyConcept.find((node) => node.tier === "mastered")!;
  const struggling = everyConcept.find((node) => node.tier === "struggling")!;
  const learning = everyConcept.find((node) => node.tier === "learning")!;
  const text = (node: GraphNode) => nodeUses(node, 3).map((use) => use.text).join(" ");

  it("quotes the mastered cut-off the app uses", () => {
    const cut = [0.94, 0.95, 0.96].find((score) => tierFor(score) === "mastered")!;
    expect(tierFor(cut - 0.01)).not.toBe("mastered");
    expect(text(mastered)).toContain(`above the ${cut.toFixed(2)} mastery cut-off`);
    expect(text(mastered)).not.toMatch(/0\.75/);
  });

  it("puts a struggling concept near the front of review, a learning one mid-queue", () => {
    expect(text(struggling)).toContain("near the front");
    expect(text(learning)).toContain("mid-queue");
  });
});
