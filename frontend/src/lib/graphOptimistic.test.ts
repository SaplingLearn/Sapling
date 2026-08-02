import { describe, expect, it } from "vitest";
import { dropOptimisticConcept, reconcileNodes, retargetEdges } from "./graphOptimistic";

/** Pure state math for the manual add-concept flow (#330): the UI adds an
 * optimistic `node-new-*` entry immediately, then swaps in the canonical row
 * the backend returns — or drops the optimistic entry when the write fails. */

const TEMP = "node-new-123";
const CANON = { id: "n-canon", mastery_score: 0.4, mastery_tier: "learning" };

const nodes = [
  { id: "n-root", name: "Math 210", mastery_tier: "subject_root", mastery_score: 0 },
  { id: TEMP, name: "Recursion", mastery_tier: "unexplored", mastery_score: 0 },
];

describe("reconcileNodes", () => {
  it("replaces the optimistic id (and mastery fields) with the canonical row", () => {
    const out = reconcileNodes(nodes, TEMP, CANON);
    expect(out.map((n) => n.id)).toEqual(["n-root", "n-canon"]);
    expect(out[1].mastery_tier).toBe("learning");
    expect(out[1].mastery_score).toBe(0.4);
  });

  it("drops the optimistic node when the canonical row is already rendered (merge)", () => {
    const withCanon = [...nodes, { id: "n-canon", name: "Recursion", mastery_tier: "learning", mastery_score: 0.4 }];
    const out = reconcileNodes(withCanon, TEMP, CANON);
    expect(out.map((n) => n.id)).toEqual(["n-root", "n-canon"]);
  });

  it("absorbs a live stream-* placeholder for the same concept (PR #485 review)", () => {
    // A tutor turn can introduce `stream-<normalized-name>` placeholders that
    // haven't been swapped for real ids yet. Manually re-adding that concept
    // merges server-side, so the client must not end up rendering both.
    const withPlaceholder = [
      ...nodes,
      { id: "stream-recursion", name: "Recursion", mastery_tier: "unexplored", mastery_score: 0 },
    ];
    const out = reconcileNodes(withPlaceholder, TEMP, { ...CANON, concept_name: "  RECURSION " });
    expect(out.map((n) => n.id)).toEqual(["n-root", "n-canon"]);
  });

  it("keeps a same-named node that is NOT a placeholder (distinct real rows)", () => {
    const withReal = [
      ...nodes,
      { id: "n-other", name: "Recursion", mastery_tier: "learning", mastery_score: 0.4 },
    ];
    const out = reconcileNodes(withReal, TEMP, { ...CANON, concept_name: "Recursion" });
    expect(out.map((n) => n.id)).toEqual(["n-root", "n-canon", "n-other"]);
  });
});

describe("retargetEdges", () => {
  it("retargets optimistic edge endpoints to the canonical id", () => {
    const out = retargetEdges([{ source: "n-root", target: TEMP, strength: 0.4 }], TEMP, "n-canon");
    expect(out).toEqual([{ source: "n-root", target: "n-canon", strength: 0.4 }]);
  });

  it("drops self-loops and duplicates created by the merge", () => {
    const out = retargetEdges(
      [
        { source: "n-root", target: TEMP },
        { source: "n-root", target: "n-canon" }, // already present → the retargeted copy is a dupe
        { source: TEMP, target: TEMP },
      ],
      TEMP,
      "n-canon",
    );
    expect(out).toEqual([{ source: "n-root", target: "n-canon" }]);
  });
});

describe("dropOptimisticConcept", () => {
  it("removes the optimistic node and every edge touching it", () => {
    const out = dropOptimisticConcept(nodes, [{ source: "n-root", target: TEMP }], TEMP);
    expect(out.nodes.map((n) => n.id)).toEqual(["n-root"]);
    expect(out.edges).toEqual([]);
  });
});
