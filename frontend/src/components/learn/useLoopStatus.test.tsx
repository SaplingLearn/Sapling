// @vitest-environment jsdom
/** PKG-13 fix round → PKG-14b (spec §11.2): the Learn branch never blocks on the
 *  loop probe, and after launch it never fails OPEN to the legacy tree.
 *  - a definitive {active: true} → the loop; {active: false} (the kill switch,
 *    or the gate's 404 that getLoopStatus resolves to it) → legacy, final;
 *  - a failed probe or no answer within LOOP_STATUS_TIMEOUT_MS → "error" (the
 *    retry state), never legacy;
 *  - retry() re-runs the GET; a late definitive answer still wins. */
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const getLoopStatus = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ getLoopStatus }));

import { LOOP_STATUS_TIMEOUT_MS, useLoopStatus } from "./useLoopStatus";

const never = () => new Promise<{ active: boolean }>(() => {});

beforeEach(() => {
  vi.useFakeTimers();
  getLoopStatus.mockReset();
});
afterEach(() => vi.useRealTimers());

describe("useLoopStatus", () => {
  it("unresolved while the probe is in flight, the retry state once the timeout passes", async () => {
    getLoopStatus.mockImplementation(never);
    const { result } = renderHook(() => useLoopStatus("u1", true));
    expect(result.current.status).toBeNull();
    await act(async () => { await vi.advanceTimersByTimeAsync(LOOP_STATUS_TIMEOUT_MS - 1); });
    expect(result.current.status).toBeNull();
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(result.current.status).toBe("error");
  });

  it("a late {active: true} after the timeout switches to the loop", async () => {
    let answer: (v: { active: boolean }) => void = () => {};
    getLoopStatus.mockImplementation(() => new Promise((r) => { answer = r; }));
    const { result } = renderHook(() => useLoopStatus("u1", true));
    await act(async () => { await vi.advanceTimersByTimeAsync(LOOP_STATUS_TIMEOUT_MS); });
    expect(result.current.status).toBe("error");
    await act(async () => { answer({ active: true }); });
    expect(result.current.status).toBe(true);
  });

  it("a failed probe is the retry state — never legacy — and is not retried on its own", async () => {
    getLoopStatus.mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useLoopStatus("u1", true));
    await act(async () => { await Promise.resolve(); });
    expect(result.current.status).toBe("error");
    await act(async () => { await vi.advanceTimersByTimeAsync(LOOP_STATUS_TIMEOUT_MS * 10); });
    expect(getLoopStatus).toHaveBeenCalledTimes(1);
    expect(result.current.status).toBe("error");
  });

  it("retry() re-runs the GET, unresolved until it answers", async () => {
    getLoopStatus.mockRejectedValueOnce(new Error("boom"));
    let answer: (v: { active: boolean }) => void = () => {};
    getLoopStatus.mockImplementationOnce(() => new Promise((r) => { answer = r; }));
    const { result } = renderHook(() => useLoopStatus("u1", true));
    await act(async () => { await Promise.resolve(); });
    expect(result.current.status).toBe("error");
    await act(async () => { result.current.retry(); });
    expect(getLoopStatus).toHaveBeenCalledTimes(2);
    expect(result.current.status).toBeNull();
    await act(async () => { answer({ active: true }); });
    expect(result.current.status).toBe(true);
  });

  it("a definitive {active: false} is final: legacy, no retry", async () => {
    getLoopStatus.mockResolvedValue({ active: false });
    const { result } = renderHook(() => useLoopStatus("u1", true));
    await act(async () => { await vi.advanceTimersByTimeAsync(LOOP_STATUS_TIMEOUT_MS * 10); });
    expect(result.current.status).toBe(false);
    expect(getLoopStatus).toHaveBeenCalledTimes(1);
  });

  it("a fast {active: true} renders the loop with no flash", async () => {
    getLoopStatus.mockResolvedValue({ active: true });
    const { result } = renderHook(() => useLoopStatus("u1", true));
    await act(async () => { await Promise.resolve(); });
    expect(result.current.status).toBe(true);
  });
});
