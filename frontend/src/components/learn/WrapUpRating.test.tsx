// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { __resetFeedbackPacingForTests, tryClaimFeedbackSlot } from "@/lib/feedbackPacing";
import { claimWrapUpAsk, useWrapUpAsk } from "./WrapUpRating";

afterEach(() => {
  __resetFeedbackPacingForTests();
  localStorage.clear();
});

describe("useWrapUpAsk (PR #866 review U9)", () => {
  it("gives the feedback slot back when the wrap-up goes before its rating card ever mounted", () => {
    const { result, rerender } = renderHook(({ close }) => useWrapUpAsk(close), {
      initialProps: { close: { id: "c1" } as unknown },
    });
    expect(claimWrapUpAsk("s1")).toBe(true);
    act(() => result.current[1]({ sessionId: "s1" }));
    expect(result.current[0]).toEqual({ sessionId: "s1" });
    expect(tryClaimFeedbackSlot("global")).toBe(false); // the wrap-up holds it

    rerender({ close: null }); // e.g. a new session started; WrapUpRating never rendered
    expect(result.current[0]).toBeNull(); // the ask is not shown with no close
    expect(tryClaimFeedbackSlot("global")).toBe(true); // …and the slot is free
  });

  it("gives the slot back when the screen unmounts with the ask open", () => {
    const { result, unmount } = renderHook(() => useWrapUpAsk({ id: "c1" }));
    expect(claimWrapUpAsk("s2")).toBe(true);
    act(() => result.current[1]({ sessionId: "s2" }));
    unmount();
    expect(tryClaimFeedbackSlot("global")).toBe(true);
  });
});
