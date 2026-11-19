// @vitest-environment jsdom
/**
 * The session panel (PR #866 U3, U4): each planned concept is labelled by its
 * kind alone — the same label the plan card's badge shows — and the knowledge
 * map's key is the palette the map is drawn in (mastery colours), tier by
 * tier, so the key under the map always describes the dots above it.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import React from "react";

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

function panel(plan: React.ComponentProps<typeof SessionPanel>["plan"]) {
  return render(
    <SessionPanel
      plan={plan}
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
    const rows = within(screen.getByRole("region", { name: "Plan" })).getAllByRole("listitem");
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
    expect(items.map((li) => li.textContent)).toEqual(
      (["mastered", "learning", "struggling", "unexplored"] as const).map((t) => TIER_LABEL[t]),
    );
    expect(items.map((li) => li.querySelector("i")!.style.background)).toEqual(
      (["mastered", "learning", "struggling", "unexplored"] as const).map((t) => rgb(MASTERY_PALETTE[t])),
    );
    expect(screen.getByTestId("map-slot")).toBeTruthy();
  });
});
