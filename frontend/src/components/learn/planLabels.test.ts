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
