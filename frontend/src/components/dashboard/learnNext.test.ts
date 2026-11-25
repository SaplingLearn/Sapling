import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({ getRecommendations: vi.fn() }));
vi.mock("@/lib/studyApi", () => ({ getStudyNext: vi.fn() }));

import { getRecommendations } from "@/lib/api";
import { getStudyNext } from "@/lib/studyApi";
import { fetchLearnNext } from "./learnNext";

const due = {
  node_id: "n1", concept_name: "Arrays", course_id: "c1", reason: "due" as const,
  p_known: 0.5, band: "develop" as const, due_at: "2026-11-07T00:00:00Z", open_misconceptions: 0,
};

afterEach(() => vi.clearAllMocks());

describe("fetchLearnNext (W8.6/W8.7)", () => {
  it("flags off: the graph recommendations, scoped to the semester, and no buckets", async () => {
    vi.mocked(getRecommendations).mockResolvedValue({ recommendations: [{ concept_name: "Legacy" }] });
    const out = await fetchLearnNext("u1", "Fall 2026", false);
    expect(out).toEqual({ recommendations: [{ concept_name: "Legacy" }], next: null });
    expect(getRecommendations).toHaveBeenCalledWith("u1", "Fall 2026");
    expect(getStudyNext).not.toHaveBeenCalled();
  });

  it("flags off: an unscoped read, and a failed one is an empty card", async () => {
    vi.mocked(getRecommendations).mockRejectedValue(new Error("down"));
    expect(await fetchLearnNext("u1", "", false)).toEqual({ recommendations: [], next: null });
    expect(getRecommendations).toHaveBeenCalledWith("u1", undefined);
  });

  it("flags on: one learner-next read feeds both Learn-next and the buckets", async () => {
    const next = { due: [due], misconceptions: [], ready: [] };
    vi.mocked(getStudyNext).mockResolvedValue(next);
    const out = await fetchLearnNext("u1", "Fall 2026", true);
    expect(out.next).toBe(next);
    expect(out.recommendations).toEqual([
      expect.objectContaining({ concept_name: "Arrays", node_id: "n1", course_id: "c1" }),
    ]);
    expect(getStudyNext).toHaveBeenCalledWith("u1");
    expect(getRecommendations).not.toHaveBeenCalled();
  });

  it("flags on but the read failed: the flag-off recommendations, no buckets", async () => {
    vi.mocked(getStudyNext).mockRejectedValue(new Error("503"));
    vi.mocked(getRecommendations).mockResolvedValue({ recommendations: [{ concept_name: "Legacy" }] });
    expect(await fetchLearnNext("u1", "", true)).toEqual({
      recommendations: [{ concept_name: "Legacy" }],
      next: null,
    });
  });
});
