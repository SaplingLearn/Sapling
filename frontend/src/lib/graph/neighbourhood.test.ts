import { describe, it, expect } from "vitest";
import { hashSeed, type GraphEdge, type GraphNode } from "@/lib/data";
import { BACKFILL_STRENGTH, siblingsFor } from "./neighbourhood";

const node = (id: string, over: Partial<GraphNode> = {}): GraphNode => ({
  id,
  name: id,
  subject: "CS101",
  color: "#7b4b99",
  mastery_tier: "learning",
  mastery_score: 0.5,
  course_id: "c1",
  ...over,
});

const NODES: GraphNode[] = [
  node("subject_root__c1", { name: "CS101", is_subject_root: true, mastery_tier: "mastered" }),
  node("recursion", { name: "Recursion", mastery_score: 0.29, mastery_tier: "struggling" }),
  node("base-cases", { name: "Base cases", mastery_score: 0.52 }),
  node("stack-frames", { name: "Stack frames", mastery_score: 0.3, mastery_tier: "struggling" }),
  node("tail-recursion", { name: "Tail recursion", mastery_score: 0.12, mastery_tier: "struggling" }),
  node("closures", { name: "Closures", mastery_score: 0.7 }),
  node("eigenvalues", { name: "Eigenvalues", course_id: "c2", subject: "MATH210" }),
];

const EDGES: GraphEdge[] = [
  { source: "subject_root__c1", target: "recursion", strength: 0.7 },
  { source: "recursion", target: "base-cases", strength: 0.9 },
  { source: "stack-frames", target: "recursion", strength: 0.4 },
  { source: "recursion", target: "tail-recursion", strength: 0.6 },
];

describe("siblingsFor", () => {
  it("returns real neighbours by descending strength, in either edge direction", () => {
    const sibs = siblingsFor("recursion", NODES, EDGES);
    expect(sibs.map((s) => s.id)).toEqual(["base-cases", "tail-recursion", "stack-frames"]);
    expect(sibs.map((s) => s.strength)).toEqual([0.9, 0.6, 0.4]);
  });

  it("excludes the synthetic subject-root hub, which is wired to every concept", () => {
    const sibs = siblingsFor("recursion", NODES, EDGES, 5);
    expect(sibs.map((s) => s.id)).not.toContain("subject_root__c1");
  });

  it("carries the fields the mark needs off each neighbour", () => {
    const [first] = siblingsFor("recursion", NODES, EDGES, 1);
    expect(first).toEqual({
      id: "base-cases",
      name: "Base cases",
      mastery: 0.52,
      tier: "learning",
      strength: 0.9,
    });
  });

  it("backfills with same-course peers, ordered by hashSeed, when there aren't enough edges", () => {
    // "closures" is the only unedged same-course concept left.
    const sibs = siblingsFor("recursion", NODES, EDGES, 4);
    expect(sibs.map((s) => s.id)).toEqual([
      "base-cases",
      "tail-recursion",
      "stack-frames",
      "closures",
    ]);
    expect(sibs[3].strength).toBe(BACKFILL_STRENGTH);
  });

  it("orders the backfill by hashSeed, not by array order", () => {
    const isolated = node("lonely", { name: "Lonely" });
    const peers = ["p-alpha", "p-beta", "p-gamma", "p-delta"].map((id) => node(id));
    const expected = [...peers]
      .sort((a, b) => hashSeed(a.id) - hashSeed(b.id))
      .slice(0, 3)
      .map((p) => p.id);

    const forward = siblingsFor("lonely", [isolated, ...peers], []);
    const reversed = siblingsFor("lonely", [isolated, ...[...peers].reverse()], []);

    expect(forward.map((s) => s.id)).toEqual(expected);
    // Same graph, different array order → same answer.
    expect(reversed.map((s) => s.id)).toEqual(expected);
  });

  it("never backfills across courses", () => {
    const sibs = siblingsFor("recursion", NODES, EDGES, 6);
    expect(sibs.map((s) => s.id)).not.toContain("eigenvalues");
    // Five concepts in c1; the centre is one of them, so four are available.
    expect(sibs).toHaveLength(4);
  });

  it("skips the backfill entirely when the centre has no course", () => {
    const orphan = node("orphan", { course_id: "" });
    const others = [node("x", { course_id: "" }), node("y", { course_id: "" })];
    expect(siblingsFor("orphan", [orphan, ...others], [])).toEqual([]);
  });

  it("returns nothing for an unknown centre, an empty graph, or n <= 0", () => {
    expect(siblingsFor("nope", NODES, EDGES)).toEqual([]);
    expect(siblingsFor("recursion", [], [])).toEqual([]);
    expect(siblingsFor("recursion", NODES, EDGES, 0)).toEqual([]);
  });

  it("keeps the strongest edge when a pair is joined more than once, and never self-links", () => {
    const dupes: GraphEdge[] = [
      { source: "recursion", target: "base-cases", strength: 0.2 },
      { source: "base-cases", target: "recursion", strength: 0.8 },
      { source: "recursion", target: "recursion", strength: 1 },
    ];
    const sibs = siblingsFor("recursion", NODES, dupes, 1);
    expect(sibs).toEqual([
      { id: "base-cases", name: "Base cases", mastery: 0.52, tier: "learning", strength: 0.8 },
    ]);
  });

  it("is deterministic across repeated calls", () => {
    const a = siblingsFor("recursion", NODES, EDGES, 4);
    const b = siblingsFor("recursion", NODES, EDGES, 4);
    expect(a).toEqual(b);
  });
});
