// @vitest-environment jsdom
/**
 * The session panel (PR #866 U3, U4): each planned concept is labelled by its
 * kind alone — the same label the plan card's badge shows — and the knowledge
 * map's key is the palette the map is drawn in (mastery colours), tier by
 * tier, so the key under the map always describes the dots above it.
 * W3.1b: when LoopLearn keeps GET /plan `prereq_edges` after approve, a compact
 * “How these connect” list appears under the plan (absent when empty).
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import React from "react";
import type { LoopPlanPrereqEdge } from "@/lib/api";

vi.mock("next/link", () => ({
  default: ({ children, href, ...rest }: { children: React.ReactNode; href: string }) => <a href={href} {...rest}>{children}</a>,
}));

import { MASTERY_PALETTE, TIER_LABEL } from "@/lib/graph/nodeStyle";
import { SessionPanel } from "./SessionPanel";

afterEach(cleanup);

/** jsdom normalises colours to rgb(); the palette is hex. */
function rgb(hex: string): string {
  const n = parseInt(hex.slice(1), 16);
  return `rgb(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255})`;
}

function panel(
  plan: React.ComponentProps<typeof SessionPanel>["plan"],
  opts: { prereqEdges?: LoopPlanPrereqEdge[]; names?: Map<string, string> } = {},
) {
  return render(
    <SessionPanel
      plan={plan}
      prereqEdges={opts.prereqEdges}
      names={opts.names}
      currentNodeId="n1"
      skills={[]}
      dueCount={0}
      dueHref="/study"
      learnerChip={null}
      hasLearner={false}
      map={<div data-testid="map-slot" />}
      treeHref="/tree"
      showTreeLink
      onHide={() => {}}
    />,
  );
}

describe("SessionPanel", () => {
  it("labels each planned concept by its kind alone", () => {
    panel([
      { node_id: "n1", concept_name: "Variables and Types", kind: "started" },
      // a stale non-goal reason (the pre-fix "related") never overrides the kind
      { node_id: "n2", concept_name: "Algorithms", kind: "new", reason: "related" },
      { node_id: "n3", concept_name: "Loops", kind: "review" },
      { node_id: "n4", concept_name: "Functions", kind: "sibling", reason: "prerequisite" },
    ]);
    const planList = within(screen.getByRole("region", { name: "Plan" })).getAllByRole("list")[0];
    const rows = within(planList).getAllByRole("listitem");
    expect(rows.map((r) => r.textContent)).toEqual([
      "1Variables and TypesKeep practicing",
      "2AlgorithmsNew",
      "3LoopsDue for review",
      "4FunctionsRelated practice",
    ]);
    expect(rows[0].getAttribute("aria-current")).toBe("step");
  });

  it("keys the map with the palette and the tier names the map is drawn in", () => {
    panel(null);
    const key = screen.getByRole("list", { name: "Map key" });
    const items = within(key).getAllByRole("listitem");
    expect(items.map((li) => li.textContent)).toEqual([
      ...(["mastered", "learning", "struggling", "unexplored"] as const).map((t) => TIER_LABEL[t]),
      "Practiced",
    ]);
    expect(items.slice(0, 4).map((li) => li.querySelector("i")!.style.background)).toEqual(
      (["mastered", "learning", "struggling", "unexplored"] as const).map((t) => rgb(MASTERY_PALETTE[t])),
    );
    expect(screen.getByTestId("tutor-map-key-practiced")).toHaveTextContent("Practiced");
    expect(screen.getByTestId("map-slot")).toBeTruthy();
  });

  it("omits the dependency block when there are no prereq edges", () => {
    panel(
      [
        { node_id: "n1", concept_name: "Binary", kind: "new" },
        { node_id: "n2", concept_name: "Operators", kind: "new" },
      ],
      { prereqEdges: [] },
    );
    expect(screen.queryByTestId("session-plan-deps")).toBeNull();
  });

  it("omits the dependency block when prereqEdges is omitted", () => {
    panel([{ node_id: "n1", concept_name: "Binary", kind: "new" }]);
    expect(screen.queryByTestId("session-plan-deps")).toBeNull();
  });

  it("lists A → B under the plan when prereq edges are present", () => {
    panel(
      [
        { node_id: "n1", concept_name: "Binary", kind: "new" },
        { node_id: "n2", concept_name: "Operators", kind: "new" },
      ],
      { prereqEdges: [{ prerequisite: "n1", dependent: "n2" }] },
    );
    const block = screen.getByTestId("session-plan-deps");
    expect(block).toHaveAccessibleName("How these connect");
    const edge = screen.getByTestId("session-plan-dep-n1-n2");
    expect(edge.textContent).toBe("Binary → Operators");
    expect(edge).toHaveAccessibleName("Binary is a prerequisite for Operators");
  });

  it("falls back to the names map for an edge endpoint not on the plan list", () => {
    panel(
      [{ node_id: "n2", concept_name: "Operators", kind: "new" }],
      {
        prereqEdges: [{ prerequisite: "n1", dependent: "n2" }],
        names: new Map([["n1", "Binary Numbers"]]),
      },
    );
    expect(screen.getByTestId("session-plan-dep-n1-n2").textContent).toBe("Binary Numbers → Operators");
  });
});
