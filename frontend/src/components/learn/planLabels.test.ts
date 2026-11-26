/**
 * PR #866 U3: each planned concept carries ONE label, from its kind, and a goal
 * reason only in a goal session — so no line under a concept can contradict
 * its badge (the bug: "Related practice" beside "New", on every concept).
 */
import { describe, expect, it } from "vitest";
import { planGoalReason, planKind } from "./planLabels";

describe("planKind", () => {
  it("names each kind the planner sends", () => {
    expect(planKind("review")?.label).toBe("Due for review");
    expect(planKind("new")?.label).toBe("New");
    expect(planKind("started")?.label).toBe("Keep practicing");
    expect(planKind("sibling")?.label).toBe("Related practice");
  });

  it("knows nothing else, prototype names included", () => {
    expect(planKind("related")).toBeNull();
    expect(planKind("constructor")).toBeNull();
    expect(planKind("")).toBeNull();
  });
});

describe("planGoalReason", () => {
  it("says why a goal session plans the concept", () => {
    expect(planGoalReason("goal")).toBe("Your selected goal");
    expect(planGoalReason("prerequisite")).toBe("Prerequisite for your goal");
  });

  it("shows nothing for a reason that only repeats (or contradicts) the kind", () => {
    // what the server sent before the fix, outside a goal
    expect(planGoalReason("related")).toBeNull();
    expect(planGoalReason("review")).toBeNull();
    expect(planGoalReason(undefined)).toBeNull();
    expect(planGoalReason("toString")).toBeNull();
  });
});

describe("planKindLabel: one label per kind, the board's under plan_v2", () => {
  it("the badge's words off, the board's on; an unknown kind has none either way", async () => {
    const { planKindLabel } = await import("./planLabels");
    expect(["review", "new", "started", "sibling"].map((k) => planKindLabel(k))).toEqual(["Due for review", "New", "Keep practicing", "Related practice"]);
    expect(["review", "new", "started", "sibling"].map((k) => planKindLabel(k, true))).toEqual(["Quick review", "New", "Practice", "Practice"]);
    expect(planKindLabel("mystery", true)).toBeNull();
    expect(planKindLabel("toString", true)).toBeNull();
  });

  it("the transcript's plan says the same words as the plan card", async () => {
    const { planTurnText } = await import("./loopHistory");
    const plan = [{ node_id: "a", concept_name: "Stacks", kind: "review" }, { node_id: "b", concept_name: "Queues", kind: "sibling" }];
    expect(planTurnText(plan, true)).toBe("Here's today's plan. Quick reviews come first, then what's new, then practice.\n\n1. Stacks — Quick review\n2. Queues — Practice");
    expect(planTurnText(plan)).toContain("1. Stacks — Due for review");
  });
});

