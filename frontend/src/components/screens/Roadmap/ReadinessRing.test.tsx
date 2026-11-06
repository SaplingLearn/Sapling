// @vitest-environment jsdom
/**
 * The readiness ring's tier split (§3.6/§3.8).
 *
 * These are invariant tests, not pixel tests: what must hold is that the
 * slices sum to the figure the ring prints, that unstarted work can never
 * claim a slice, and that the colour scale is the shared `TIER_OPACITY` ramp
 * rather than a palette invented here.
 */
import React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ReadinessRing, readinessSegments } from "./ReadinessRing";
import { TIER_OPACITY } from "@/lib/graph/nodeStyle";
import type { RoadmapSubtopic } from "@/lib/api";

afterEach(cleanup);

function row(overrides: Partial<RoadmapSubtopic> = {}): RoadmapSubtopic {
  const mastery = overrides.mastery ?? 0.8;
  return {
    node_id: "n1",
    concept_name: "Mitochondria",
    mastery,
    tier: "mastered",
    freshness: 1,
    is_stale: false,
    weight: 1,
    contribution: mastery,
    color: "#4FA574",
    times_studied: 1,
    last_studied_at: null,
    in_cycle: false,
    ...overrides,
  };
}

const HUE = "#4FA574";

describe("readinessSegments", () => {
  it("splits the figure without re-deriving it", () => {
    // Two rows contributing 0.9 and 0.3; the server says 0.6.
    const segs = readinessSegments(
      [
        row({ node_id: "a", tier: "mastered", contribution: 0.9 }),
        row({ node_id: "b", tier: "struggling", contribution: 0.3 }),
      ],
      0.6,
    );
    const total = segs.reduce((s, x) => s + x.share, 0);
    expect(total).toBeCloseTo(0.6, 10);
    // 0.9 : 0.3 is 3:1, so the slices are 0.45 and 0.15 of the ring.
    expect(segs.find(s => s.tier === "mastered")!.share).toBeCloseTo(0.45, 10);
    expect(segs.find(s => s.tier === "struggling")!.share).toBeCloseTo(0.15, 10);
  });

  it("honours a readiness the contributions alone would not produce", () => {
    // `subtopic_readiness` takes a weight this client never sees, so the
    // split must follow the server's figure rather than the raw sum.
    const segs = readinessSegments([row({ contribution: 0.8 })], 0.2);
    expect(segs.reduce((s, x) => s + x.share, 0)).toBeCloseTo(0.2, 10);
  });

  it("gives unstarted concepts a zero slice but still counts them", () => {
    const segs = readinessSegments(
      [
        row({ node_id: "a", tier: "mastered", contribution: 0.9 }),
        row({ node_id: "b", tier: "unexplored", mastery: 0, contribution: 0 }),
        row({ node_id: "c", tier: "unexplored", mastery: 0, contribution: 0 }),
      ],
      0.3,
    );
    const unexplored = segs.find(s => s.tier === "unexplored")!;
    expect(unexplored.share).toBe(0);
    // Dropping the row would delete the explanation for the ring's gap.
    expect(unexplored.count).toBe(2);
  });

  it("returns every tier in one canonical order, best first", () => {
    expect(readinessSegments([], 0).map(s => s.tier)).toEqual([
      "mastered",
      "learning",
      "struggling",
      "unexplored",
    ]);
  });

  it("does not divide by zero when nothing has been studied", () => {
    const segs = readinessSegments([row({ tier: "unexplored", contribution: 0 })], 0);
    expect(segs.every(s => Number.isFinite(s.share))).toBe(true);
    expect(segs.reduce((s, x) => s + x.share, 0)).toBe(0);
  });
});

describe("ReadinessRing", () => {
  const rows = [
    row({ node_id: "a", tier: "mastered", contribution: 0.9 }),
    row({ node_id: "b", tier: "learning", contribution: 0.5 }),
    row({ node_id: "c", tier: "unexplored", mastery: 0, contribution: 0 }),
  ];

  it("draws one slice per contributing tier, and none for unstarted work", () => {
    render(<ReadinessRing readiness={0.7} exam={null} rows={rows} baseHue={HUE} />);

    expect(screen.getByTestId("roadmap-ring-slice-mastered")).toBeInTheDocument();
    expect(screen.getByTestId("roadmap-ring-slice-learning")).toBeInTheDocument();
    expect(screen.queryByTestId("roadmap-ring-slice-unexplored")).not.toBeInTheDocument();
  });

  it("paints each slice with the shared tier ramp, not a palette of its own", () => {
    render(<ReadinessRing readiness={0.7} exam={null} rows={rows} baseHue={HUE} />);

    const mastered = screen.getByTestId("roadmap-ring-slice-mastered");
    expect(mastered).toHaveAttribute("stroke", HUE);
    expect(mastered.getAttribute("stroke-opacity")).toBe(String(TIER_OPACITY.mastered));
    expect(
      screen.getByTestId("roadmap-ring-slice-learning").getAttribute("stroke-opacity"),
    ).toBe(String(TIER_OPACITY.learning));
  });

  it("keys the slices, listing unstarted concepts so the gap is explained", () => {
    render(<ReadinessRing readiness={0.7} exam={null} rows={rows} baseHue={HUE} />);

    expect(screen.getByTestId("roadmap-ring-key")).toBeInTheDocument();
    expect(screen.getByTestId("roadmap-ring-key-unexplored")).toHaveTextContent("Not started");
    expect(screen.getByTestId("roadmap-ring-key-unexplored")).toHaveTextContent("+0%");
  });

  it("falls back to the single accent arc when it has no rows to split", () => {
    render(<ReadinessRing readiness={0.5} exam={null} baseHue={HUE} />);

    expect(screen.getByText("50%")).toBeInTheDocument();
    expect(screen.queryByTestId("roadmap-ring-key")).not.toBeInTheDocument();
    expect(screen.queryByTestId("roadmap-ring-slice-mastered")).not.toBeInTheDocument();
  });
});
