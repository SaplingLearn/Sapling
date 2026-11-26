// @vitest-environment jsdom
/**
 * The rebuilt check-in result and plan (Tutor redesign phase 4, `plan_v2`)
 * against its design board, `../__fixtures__/plan.design.html`, kept verbatim:
 * the words the rebuild says are pulled from it, so a drift from the design
 * fails here (words and structure, not pixels: jsdom has no layout). The kind
 * words are planLabels.ts's (shared with the session panel and the
 * transcript); the board's "Quick review" / "Practice" wait for the sidebar.
 */
import fs from "node:fs";
import path from "node:path";
import React from "react";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const flags: Record<string, string> = {};
vi.mock("@/context/FlagsContext", () => ({ useFlag: (k: string) => flags[k] ?? "off" }));

import type { LoopDiagnosis, LoopDiagnosisSkill, LoopPlanConcept } from "@/lib/api";
import { PLAN_V2_COPY, PlanSlot, PlanV2, nameList, planIntro, planRowLabel, startingRows } from "./PlanV2";

afterEach(() => {
  cleanup();
  for (const k of Object.keys(flags)) delete flags[k];
});

const DESIGN = fs.readFileSync(path.join(__dirname, "../__fixtures__/plan.design.html"), "utf8").replace(/&#39;|&rsquo;|’/g, "'");
const names = new Map([["st", "Stacks"], ["ht", "Hash tables"], ["cr", "Collision resolution"], ["q", "Queues"]]);
const skill = (node_id: string, observations: number): LoopDiagnosisSkill => ({
  node_id, status: observations ? "bracketed" : "untested", floor_difficulty: null, ceiling_difficulty: null,
  independent_correct: 0, independent_incorrect: 0, independent_observations: observations, observations,
  tested_difficulties: [], available_difficulties: [], contradictory_difficulties: [],
});
// The board's session, as the server sends it: the diagnosis lists by node id.
const DIAGNOSIS: LoopDiagnosis = { status: "bracketed", stop_reason: null, skills: [skill("cr", 0), skill("ht", 2), skill("st", 2)] };
const STARTING = [{ node_id: "ht", p_known: 0.14 }, { node_id: "st", p_known: 0.44 }];
const concept = (node_id: string, kind: string, p_known = 0.1): LoopPlanConcept =>
  ({ node_id, concept_name: names.get(node_id) ?? "", kind, p_known });
const PLAN = [concept("st", "review", 0.44), concept("ht", "new", 0.14), concept("cr", "new"), concept("q", "sibling")];
const EDGES = [{ prerequisite: "ht", dependent: "cr" }];

function renderPlan(props: Partial<React.ComponentProps<typeof PlanV2>> = {}) {
  const onApprove = vi.fn();
  const open = vi.fn();
  render(
    <PlanV2 diagnosis={DIAGNOSIS} names={names} plan={PLAN} prereqEdges={EDGES} starting={STARTING} busy={false}
      loadFailed={false} onApprove={onApprove} onRetry={() => {}} goal={{ has: true, disabled: false, open }} goalRef={() => {}} {...props} />,
  );
  return { onApprove, open };
}

describe("what the plan says", () => {
  it("each planned concept has one label; a prerequisite earlier in the plan reads in it", () => {
    expect(PLAN.map((_, i) => planRowLabel(PLAN, i, EDGES))).toEqual(["Due for review", "New", "New, after Hash tables", "Related practice"]);
    // a prerequisite later in the plan, or not in it, says nothing
    expect(planRowLabel(PLAN, 1, [{ prerequisite: "cr", dependent: "ht" }, { prerequisite: "x", dependent: "ht" }])).toBe("New");
    expect(planRowLabel([concept("x", "mystery")], 0, [])).toBeNull();
  });

  it("where you're starting: the check-in's concepts in plan order; one it never reached is Not started, never the prior", () => {
    const rows = startingRows(DIAGNOSIS, STARTING, PLAN, names);
    expect(rows.map((r) => [r.name, r.level])).toEqual([["Stacks", "develop"], ["Hash tables", "novice"], ["Collision resolution", "not_started"]]);
    expect(rows[2].p).toBeNull();
    // measured but not planned: still shown, after the planned ones
    const off = startingRows({ ...DIAGNOSIS, skills: [skill("q", 1), skill("st", 2)] }, [{ node_id: "q", p_known: 0.9 }, ...STARTING], [PLAN[0]], names);
    expect(off.map((r) => [r.name, r.level])).toEqual([["Stacks", "develop"], ["Queues", "profic"]]);
    expect(startingRows(null, STARTING, PLAN, names)).toEqual([]);
  });

  it("the tutor's line comes from the rows", () => {
    expect(planIntro(startingRows(DIAGNOSIS, STARTING, PLAN, names))).toBe(
      "Thanks. You have a head start on Stacks. Hash tables and Collision resolution are new to you. Here's where you're starting and what I suggest for today.",
    );
    expect(planIntro([{ id: "a", name: "Queues", level: "novice", p: 0.1 }])).toBe(
      "Thanks. Queues is new to you. Here's where you're starting and what I suggest for today.",
    );
    expect(planIntro([])).toBe("Here's what I suggest for today."); // no check-in
    expect(nameList(["A", "B", "C"])).toBe("A, B and C");
  });
});

describe("parity with the design board", () => {
  it.each([
    PLAN_V2_COPY.starting, PLAN_V2_COPY.today, PLAN_V2_COPY.suggest, PLAN_V2_COPY.changeGoal,
    "Start this plan", "Developing", "Getting started", "Not started", "New", "Check-in", "Plan", "Learn", "Wrap up",
  ])("the board says %j", (text) => {
    expect(DESIGN).toContain(text);
  });

  it("the board's prerequisite label is the rebuild's (the concept keeps its own capitals)", () => {
    expect(DESIGN.toLowerCase()).toContain(planRowLabel(PLAN, 2, EDGES)!.toLowerCase());
  });

  it("the board's order: the tutor's line, where you're starting, today's plan, its two actions", () => {
    renderPlan();
    const root = screen.getByTestId("loop-plan-v2");
    const order = [
      within(root).getByTestId("loop-plan-intro"),
      within(root).getByRole("heading", { name: PLAN_V2_COPY.starting }),
      within(root).getByRole("heading", { name: PLAN_V2_COPY.today }),
      within(root).getByTestId("loop-plan-concept-q"),
      within(root).getByTestId("loop-plan-approve"),
    ];
    for (let i = 1; i < order.length; i += 1) {
      expect(order[i - 1].compareDocumentPosition(order[i]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
    expect(screen.getByTestId("loop-plan-intro")).toHaveFocus(); // it replaces the check-in (A135)
    const starting = screen.getByTestId("loop-plan-starting");
    expect(within(starting).getAllByRole("meter").map((m) => m.getAttribute("aria-valuetext"))).toEqual(["Developing", "Getting started", "Not started"]);
    expect(screen.getByTestId("loop-plan-kind-cr").textContent).toBe("New, after Hash tables");
    expect(screen.queryByTestId("loop-plan-deps")).toBeNull(); // folded into the labels
  });

  it("Start this plan is the one primary action; Change goal opens the goal editor", () => {
    const { onApprove, open } = renderPlan();
    expect(screen.getByTestId("loop-plan-approve").className).toContain("btn--primary");
    const change = screen.getByTestId("loop-set-goal");
    expect(change.textContent).toBe("Change goal");
    expect(change.className).not.toContain("btn--primary");
    fireEvent.click(change);
    fireEvent.click(screen.getByTestId("loop-plan-approve"));
    expect(open).toHaveBeenCalledTimes(1);
    expect(onApprove).toHaveBeenCalledTimes(1);
  });

  it("no goal yet: Set goal; the plan still loading or failed keeps its own line", () => {
    renderPlan({ goal: { has: false, disabled: true, open: () => {} }, plan: null, loadFailed: true });
    expect(screen.getByTestId("loop-set-goal").textContent).toBe("Set goal");
    expect((screen.getByTestId("loop-set-goal") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("loop-plan-intro").textContent).toBe(PLAN_V2_COPY.failed);
    expect(screen.queryByTestId("loop-plan-starting")).toBeNull();
    expect(screen.getByTestId("loop-plan-retry")).toBeTruthy();
    expect(screen.queryByTestId("loop-plan-approve")).toBeNull();
  });

  it("while the plan loads, nothing is said about the start (a measured concept never flashes Not started)", () => {
    renderPlan({ plan: null, starting: [] });
    expect(screen.getByTestId("loop-plan-intro").textContent).toBe(PLAN_V2_COPY.building);
    expect(screen.queryByTestId("loop-plan-starting")).toBeNull();
    expect(screen.queryByTestId("loop-plan-retry")).toBeNull();
  });
});

describe("PlanSlot", () => {
  const props = {
    diagnosis: DIAGNOSIS, names, plan: PLAN, prereqEdges: EDGES, starting: STARTING, busy: false, loadFailed: false,
    onApprove: () => {}, onRetry: () => {}, goal: { has: true, disabled: false, open: () => {} }, goalRef: () => {},
  };

  it("plan_v2 off: the plan card as before", () => {
    render(<PlanSlot {...props} />);
    expect(screen.queryByTestId("loop-plan-v2")).toBeNull();
    expect(screen.getByTestId("loop-plan-approve")).toBeTruthy();
    expect(screen.queryByTestId("loop-set-goal")).toBeNull(); // the header keeps Edit goal
  });

  it("plan_v2 on: the rebuilt plan", () => {
    flags.plan_v2 = "on";
    render(<PlanSlot {...props} />);
    expect(screen.getByTestId("loop-plan-v2")).toBeTruthy();
  });
});
