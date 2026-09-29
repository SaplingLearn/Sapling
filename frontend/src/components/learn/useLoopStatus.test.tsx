// @vitest-environment jsdom
/** PKG-13 fix round: the Learn branch never blocks on the loop probe, and never
 *  strands a loop student on the legacy tree once the probe does answer.
 *  - no answer within LOOP_STATUS_TIMEOUT_MS → legacy (provisional);
 *  - a failed probe → legacy (provisional) and a bounded retry;
 *  - a definitive {active: true} — even a late one — switches to the loop: the
 *    backend delegates the legacy routes to the loop for that student
 *    (routes/learn.py `_loop_delegate`), so the legacy screen would misbehave;
 *  - a definitive {active: false} is final. */
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const getLoopStatus = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ getLoopStatus }));

import { LOOP_STATUS_RETRY_MS, LOOP_STATUS_TIMEOUT_MS, useLoopStatus } from "./useLoopStatus";

const never = () => new Promise<{ active: boolean }>(() => {});

beforeEach(() => {
  vi.useFakeTimers();
  getLoopStatus.mockReset();
});
afterEach(() => vi.useRealTimers());

describe("useLoopStatus", () => {
  it("unresolved while the probe is in flight, legacy once the timeout passes", async () => {
    getLoopStatus.mockImplementation(never);
    const { result } = renderHook(() => useLoopStatus("u1", true));
    expect(result.current).toBeNull();
    await act(async () => { await vi.advanceTimersByTimeAsync(LOOP_STATUS_TIMEOUT_MS - 1); });
    expect(result.current).toBeNull();
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(result.current).toBe(false);
  });

  it("a late {active: true} after the timeout switches to the loop", async () => {
    let answer: (v: { active: boolean }) => void = () => {};
    getLoopStatus.mockImplementation(() => new Promise((r) => { answer = r; }));
    const { result } = renderHook(() => useLoopStatus("u1", true));
    await act(async () => { await vi.advanceTimersByTimeAsync(LOOP_STATUS_TIMEOUT_MS); });
    expect(result.current).toBe(false);
    await act(async () => { answer({ active: true }); });
    expect(result.current).toBe(true);
  });

  it("a failed probe is legacy for now and retried; a retry that answers active switches", async () => {
    getLoopStatus.mockRejectedValueOnce(new Error("boom")).mockResolvedValueOnce({ active: true });
    const { result } = renderHook(() => useLoopStatus("u1", true));
    await act(async () => { await Promise.resolve(); });
    expect(result.current).toBe(false);
    await act(async () => { await vi.advanceTimersByTimeAsync(LOOP_STATUS_RETRY_MS[0]); });
    expect(getLoopStatus).toHaveBeenCalledTimes(2);
    expect(result.current).toBe(true);
  });

  it("retries are bounded", async () => {
    getLoopStatus.mockRejectedValue(new Error("down"));
    const { result } = renderHook(() => useLoopStatus("u1", true));
    const total = LOOP_STATUS_RETRY_MS.reduce((a, b) => a + b, 0);
    await act(async () => { await vi.advanceTimersByTimeAsync(total * 2); });
    expect(getLoopStatus).toHaveBeenCalledTimes(1 + LOOP_STATUS_RETRY_MS.length);
    expect(result.current).toBe(false);
  });

  it("a definitive {active: false} is final: no retry", async () => {
    getLoopStatus.mockResolvedValue({ active: false });
    const { result } = renderHook(() => useLoopStatus("u1", true));
    await act(async () => { await vi.advanceTimersByTimeAsync(LOOP_STATUS_TIMEOUT_MS * 10); });
    expect(result.current).toBe(false);
    expect(getLoopStatus).toHaveBeenCalledTimes(1);
  });

  it("a fast {active: true} renders the loop with no legacy flash", async () => {
    getLoopStatus.mockResolvedValue({ active: true });
    const { result } = renderHook(() => useLoopStatus("u1", true));
    await act(async () => { await Promise.resolve(); });
    expect(result.current).toBe(true);
  });
});
