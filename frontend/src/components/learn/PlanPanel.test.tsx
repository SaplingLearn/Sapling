// @vitest-environment jsdom
/**
 * #866 K28: the plan card renders what GET /plan sends — each concept's one
 * kind badge and, in a goal session, why it is planned. GET /plan sends no
 * band, so the card has no band chip to fill (it never rendered one).
 * W3.1: when GET /plan sends prereq_edges, a compact dependency list appears
 * under the numbered concepts (absent when the list is empty).
 */
import React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { LoopPlanConcept, LoopPlanPrereqEdge } from "@/lib/api";
import { orderedPlanEdges } from "./PlanDeps";
import { PlanPanel } from "./PlanPanel";

afterEach(cleanup);

const concept = (over: Partial<LoopPlanConcept> = {}): LoopPlanConcept => ({
  node_id: "n1", concept_name: "Binary", kind: "new", p_known: 0.35, ...over,
});

function renderPlan(
  plan: LoopPlanConcept[],
  opts: { prereqEdges?: LoopPlanPrereqEdge[]; names?: Map<string, string> } = {},
) {
  render(
    <PlanPanel
      plan={plan}
      prereqEdges={opts.prereqEdges}
      busy={false}
      loadFailed={false}
      onApprove={() => {}}
      onRetry={() => {}}
      diagnosis={null}
      names={opts.names ?? new Map()}
    />,
  );
}

describe("PlanPanel", () => {
  it("shows each concept's kind badge and its goal reason, and no other chip", () => {
    // a band a server might add is not part of GET /plan: the card ignores it
    renderPlan([concept({ reason: "prerequisite", ...({ band: "novice" } as object) })]);
    const row = screen.getByTestId("loop-plan-concept-n1");
    expect(screen.getByTestId("loop-plan-kind-n1").textContent).toBe("New");
    expect(screen.getByTestId("loop-plan-reason-n1").textContent).toBe("Prerequisite for your goal");
    expect(row.querySelectorAll(".chip")).toHaveLength(1);
    expect(row.textContent).not.toContain("Getting started");
  });

  it("outside a goal session, the kind badge is the one label", () => {
    renderPlan([concept({ kind: "review" })]);
    expect(screen.getByTestId("loop-plan-kind-n1").textContent).toBe("Due for review");
    expect(screen.queryByTestId("loop-plan-reason-n1")).toBeNull();
  });

  it("omits the dependency block when there are no prereq edges", () => {
    renderPlan([
      concept(),
      concept({ node_id: "n2", concept_name: "Operators", kind: "new" }),
    ], { prereqEdges: [] });
    expect(screen.queryByTestId("loop-plan-deps")).toBeNull();
  });

  it("omits the dependency block when prereqEdges is omitted", () => {
    renderPlan([concept()]);
    expect(screen.queryByTestId("loop-plan-deps")).toBeNull();
  });

  it("lists A → B under the plan when prereq edges are present", () => {
    renderPlan(
      [
        concept(),
        concept({ node_id: "n2", concept_name: "Operators", kind: "new", reason: "goal" }),
      ],
      { prereqEdges: [{ prerequisite: "n1", dependent: "n2" }] },
    );
    const block = screen.getByTestId("loop-plan-deps");
    expect(block).toHaveAccessibleName("How these connect");
    const edge = screen.getByTestId("loop-plan-dep-n1-n2");
    expect(edge.textContent).toBe("Binary → Operators");
    expect(edge).toHaveAccessibleName("Binary is a prerequisite for Operators");
    // approve stays the action surface
    expect(screen.getByTestId("loop-plan-approve")).toBeTruthy();
  });

  it("falls back to the names map for an edge endpoint not on the plan list", () => {
    renderPlan(
      [concept({ node_id: "n2", concept_name: "Operators", reason: "goal" })],
      {
        prereqEdges: [{ prerequisite: "n1", dependent: "n2" }],
        names: new Map([["n1", "Binary Numbers"]]),
      },
    );
    expect(screen.getByTestId("loop-plan-dep-n1-n2").textContent).toBe("Binary Numbers → Operators");
  });

  it("lists the edges in plan order, once each, and only those touching the plan", () => {
    renderPlan(
      [
        concept({ node_id: "a", concept_name: "Bits" }),
        concept({ node_id: "b", concept_name: "Bytes" }),
        concept({ node_id: "c", concept_name: "Words" }),
      ],
      {
        prereqEdges: [
          { prerequisite: "b", dependent: "c" },
          { prerequisite: "goal1", dependent: "goal2" }, // neither planned today
          { prerequisite: "a", dependent: "b" },
          { prerequisite: "b", dependent: "c" }, // a repeat
        ],
      },
    );
    const lines = screen.getByRole("list", { name: "Prerequisite dependencies" }).querySelectorAll("li");
    expect(Array.from(lines, (li) => li.getAttribute("data-testid"))).toEqual([
      "loop-plan-dep-a-b",
      "loop-plan-dep-b-c",
    ]);
  });

  it("shows order only: no mastery, score or band appears in the dependency block", () => {
    renderPlan(
      [concept({ p_known: 0.91 }), concept({ node_id: "n2", concept_name: "Operators", p_known: 0.12 })],
      { prereqEdges: [{ prerequisite: "n1", dependent: "n2" }] },
    );
    const text = screen.getByTestId("loop-plan-deps").textContent ?? "";
    expect(text).toBe("How these connectBinary → Operators");
    expect(text).not.toMatch(/\d|%|mastered|learning|struggling/i);
  });
});

describe("orderedPlanEdges", () => {
  const plan = [{ node_id: "x", concept_name: "X" }, { node_id: "y", concept_name: "Y" }];
  it("keeps an edge up to a goal target off the plan, after the planned pairs", () => {
    expect(orderedPlanEdges(
      [{ prerequisite: "y", dependent: "goal" }, { prerequisite: "x", dependent: "y" }],
      plan,
    )).toEqual([{ prerequisite: "x", dependent: "y" }, { prerequisite: "y", dependent: "goal" }]);
  });
  it("drops self-loops and returns nothing without a plan", () => {
    expect(orderedPlanEdges([{ prerequisite: "x", dependent: "x" }], plan)).toEqual([]);
    expect(orderedPlanEdges([{ prerequisite: "x", dependent: "y" }], null)).toEqual([]);
  });
});
