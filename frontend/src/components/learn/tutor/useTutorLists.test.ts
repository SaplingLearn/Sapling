// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, renderHook, waitFor } from "@testing-library/react";

const api = vi.hoisted(() => ({ getDocuments: vi.fn(), getReviewSummary: vi.fn(), getSessions: vi.fn() }));
vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), ...api }));

import { useTutorLists } from "./useTutorLists";

const summary = (flashcard: number, check: number, extra: object = {}) => ({
  due: { flashcard, check }, in_budget: 0, unservable: 0, paused: 0, budget_min: 12,
  remaining_budget_s: 720, retention_target: 0.9, ...extra,
});

afterEach(() => { cleanup(); vi.resetAllMocks(); });

describe("useTutorLists — the due count (#866 K14)", () => {
  const lists = () => renderHook(() => useTutorLists({
    userId: "u1", sessionId: null, sessionClosed: false, wantMaterials: false, studyVisible: true,
  }));

  it("counts the reviews that are due, never the never-rated cards among them", async () => {
    api.getSessions.mockResolvedValue({ sessions: [] });
    // 250 due cards, 248 of them never rated (A74's pool: new, not due reviews)
    api.getReviewSummary.mockResolvedValue(summary(250, 3, { new: 248 }));
    const { result } = lists();
    await waitFor(() => expect(result.current.dueReviews).toBe(5));
  });

  it("a server before the fix (no `new`) counts every due item", async () => {
    api.getSessions.mockResolvedValue({ sessions: [] });
    api.getReviewSummary.mockResolvedValue(summary(2, 1));
    const { result } = lists();
    await waitFor(() => expect(result.current.dueReviews).toBe(3));
  });
});
