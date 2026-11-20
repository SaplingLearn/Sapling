// @vitest-environment jsdom
/**
 * #866 K28: the plan card renders what GET /plan sends — each concept's one
 * kind badge and, in a goal session, why it is planned. GET /plan sends no
 * band, so the card has no band chip to fill (it never rendered one).
 */
import React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { LoopPlanConcept } from "@/lib/api";
import { PlanPanel } from "./PlanPanel";

afterEach(cleanup);

const concept = (over: Partial<LoopPlanConcept> = {}): LoopPlanConcept => ({
  node_id: "n1", concept_name: "Binary", kind: "new", p_known: 0.35, ...over,
});

function renderPlan(plan: LoopPlanConcept[]) {
  render(<PlanPanel plan={plan} busy={false} loadFailed={false} onApprove={() => {}} onRetry={() => {}} diagnosis={null} names={new Map()} />);
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
});
