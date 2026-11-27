import { describe, expect, it } from "vitest";
import type { LoopConceptTrend } from "@/lib/types";
import { directionCounts, rung, trendRows } from "./HintTrendPanel";

const concept = (concept_id: string, direction: LoopConceptTrend["direction"]): LoopConceptTrend => ({
  concept_id,
  weeks: [{ week_start: "2026-10-12", mean_rung: 1, steps: 3 }],
  direction,
});

describe("HintTrendPanel's helpers (spec §10 htc_k)", () => {
  it("counts each direction, zero included", () => {
    expect(directionCounts([concept("a", "falling"), concept("b", "falling"), concept("c", "insufficient")])).toEqual({
      rising: 0, flat: 0, falling: 2, insufficient: 1,
    });
  });

  it("lists the concepts with a trend, worst first, then by id", () => {
    const rows = trendRows([
      concept("z", "falling"), concept("one-week", "insufficient"), concept("b", "rising"),
      concept("a", "flat"), concept("a2", "rising"),
    ]);
    expect(rows.map(r => r.concept_id)).toEqual(["a2", "b", "a", "z"]);
  });

  it("reads a mean rung as a hint level to one decimal", () => {
    expect(rung(0)).toBe("H0");
    expect(rung(1.25)).toBe("H1.3");
    expect(rung(2)).toBe("H2");
  });
});
