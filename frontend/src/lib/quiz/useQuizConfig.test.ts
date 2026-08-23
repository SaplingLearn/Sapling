// @vitest-environment jsdom
import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";

const quizApi = vi.hoisted(() => ({ fetchQuizConfig: vi.fn() }));
vi.mock("./api", () => quizApi);

const gamification = vi.hoisted(() => ({ fetchGamificationMe: vi.fn() }));
vi.mock("@/lib/api", async importActual => {
  const actual = await importActual<typeof import("@/lib/api")>();
  return { ...actual, fetchGamificationMe: gamification.fetchGamificationMe };
});

import { resetQuizConfigCache, useQuizConfig } from "./useQuizConfig";
import { useGamificationDelta } from "./useGamificationDelta";

const CONFIG = {
  num_questions: { min: 1, max: 10, options: [3, 5, 10] },
  difficulties: ["easy", "medium", "hard", "adaptive"],
  question_types: ["multiple_choice"],
};

function me(total_xp: number, streak: number) {
  return {
    level: 3, next_level: 4, stage: "sprout", total_xp, xp_into_level: 10, xp_for_level: 100,
    level_pct: 10, streak, longest_streak: streak, daily_goal_xp: 50, today_xp: 10,
    earned_count: 1, total_count: 10,
  };
}

beforeEach(() => {
  resetQuizConfigCache();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("useQuizConfig", () => {
  it("fetches once and shares the result across mounts", async () => {
    quizApi.fetchQuizConfig.mockResolvedValue(CONFIG);
    const a = renderHook(() => useQuizConfig());
    const b = renderHook(() => useQuizConfig());
    await waitFor(() => expect(a.result.current.config).toEqual(CONFIG));
    await waitFor(() => expect(b.result.current.config).toEqual(CONFIG));
    expect(quizApi.fetchQuizConfig).toHaveBeenCalledTimes(1);
  });

  it("maps a failure to quiz error copy and lets the next mount retry", async () => {
    quizApi.fetchQuizConfig.mockRejectedValueOnce(new ApiError("down", 500));
    const first = renderHook(() => useQuizConfig());
    await waitFor(() => expect(first.result.current.error).not.toBeNull());
    expect(first.result.current.error?.code).toBe("QUIZ_INTERNAL_ERROR");

    quizApi.fetchQuizConfig.mockResolvedValue(CONFIG);
    const second = renderHook(() => useQuizConfig());
    await waitFor(() => expect(second.result.current.config).toEqual(CONFIG));
  });
});

describe("useGamificationDelta", () => {
  it("subtracts the two reads", async () => {
    gamification.fetchGamificationMe
      .mockResolvedValueOnce(me(100, 3))
      .mockResolvedValueOnce(me(130, 4));

    const { result } = renderHook(() => useGamificationDelta("u1"));
    await result.current.snapshotBefore();
    await waitFor(() => expect(result.current.before?.total_xp).toBe(100));
    await expect(result.current.deltaAfterSubmit()).resolves.toEqual({
      before: 100,
      after: 130,
      streak: 4,
    });
  });

  it("returns null when the before read failed — never an invented delta", async () => {
    gamification.fetchGamificationMe.mockRejectedValueOnce(new Error("down"));
    gamification.fetchGamificationMe.mockResolvedValueOnce(me(130, 4));

    const { result } = renderHook(() => useGamificationDelta("u1"));
    await result.current.snapshotBefore();
    await expect(result.current.deltaAfterSubmit()).resolves.toBeNull();
  });

  it("returns null when the after read failed", async () => {
    gamification.fetchGamificationMe.mockResolvedValueOnce(me(100, 3));
    gamification.fetchGamificationMe.mockRejectedValueOnce(new Error("down"));

    const { result } = renderHook(() => useGamificationDelta("u1"));
    await result.current.snapshotBefore();
    await expect(result.current.deltaAfterSubmit()).resolves.toBeNull();
  });

  it("does nothing without a user id", async () => {
    const { result } = renderHook(() => useGamificationDelta(""));
    await result.current.snapshotBefore();
    await expect(result.current.readAfter()).resolves.toBeNull();
    expect(gamification.fetchGamificationMe).not.toHaveBeenCalled();
  });
});
