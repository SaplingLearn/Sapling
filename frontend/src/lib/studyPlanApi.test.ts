import { beforeEach, expect, it, vi } from "vitest";
import { fetchJSON } from "./api";
import { getStudyPlans, updateStudyPlan, type StudyPlan } from "./studyPlanApi";

vi.mock("./api", () => ({ fetchJSON: vi.fn() }));
beforeEach(() => vi.resetAllMocks());

it("encodes scope and sends the saved version with edits", async () => {
  await getStudyPlans("user/a", "CAS CS 111", "Fall 2026");
  expect(fetchJSON).toHaveBeenLastCalledWith("/api/topic-checklist/user%2Fa/courses/CAS%20CS%20111/plans?semester=Fall+2026", { signal: undefined });
  await updateStudyPlan("u", "c", { id: "plan", version: 3 } as StudyPlan, { regenerate: true });
  expect(fetchJSON).toHaveBeenLastCalledWith("/api/topic-checklist/u/courses/c/plans/plan", {
    method: "PATCH", body: JSON.stringify({ version: 3, regenerate: true }), signal: undefined,
  });
});
