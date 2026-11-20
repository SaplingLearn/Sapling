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
// The student's flags: the `learning_loop` flag "on" unless a test says otherwise.
// `fresh` absent reads as a fresh map (FlagsContext always sets it).
const flagState = vi.hoisted(() => ({
  value: { flags: { learning_loop: "on" } as Record<string, string>, ready: true } as {
    flags: Record<string, string>; ready: boolean; fresh?: boolean;
  },
}));
vi.mock("@/context/FlagsContext", () => ({ useFlagMap: () => flagState.value }));

import { LOOP_STATUS_TIMEOUT_MS, useLoopStatus } from "./useLoopStatus";

const never = () => new Promise<{ active: boolean }>(() => {});

beforeEach(() => {
  vi.useFakeTimers();
  getLoopStatus.mockReset();
  flagState.value = { flags: { learning_loop: "on" }, ready: true };
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

  it("the learning_loop flag off is the legacy tree, final, with no probe", async () => {
    flagState.value = { flags: { learning_loop: "off" }, ready: true };
    const { result } = renderHook(() => useLoopStatus("u1", true));
    await act(async () => { await vi.advanceTimersByTimeAsync(LOOP_STATUS_TIMEOUT_MS * 10); });
    expect(result.current.status).toBe(false);
    expect(getLoopStatus).not.toHaveBeenCalled();
  });

  it("unresolved, with no probe, while the flags load; the probe runs once they say on", async () => {
    flagState.value = { flags: {}, ready: false };
    getLoopStatus.mockResolvedValue({ active: true });
    const { result, rerender } = renderHook(() => useLoopStatus("u1", true));
    await act(async () => { await vi.advanceTimersByTimeAsync(LOOP_STATUS_TIMEOUT_MS * 2); });
    expect(result.current.status).toBeNull();
    expect(getLoopStatus).not.toHaveBeenCalled();
    flagState.value = { flags: { learning_loop: "on" }, ready: true };
    rerender();
    await act(async () => { await Promise.resolve(); });
    expect(result.current.status).toBe(true);
    expect(getLoopStatus).toHaveBeenCalledTimes(1);
  });

  it("a flag map without the key (unreadable flags, nothing remembered) defers to the probe", async () => {
    flagState.value = { flags: {}, ready: true };
    getLoopStatus.mockResolvedValue({ active: false });
    const { result } = renderHook(() => useLoopStatus("u1", true));
    await act(async () => { await Promise.resolve(); });
    expect(getLoopStatus).toHaveBeenCalledTimes(1);
    expect(result.current.status).toBe(false);
  });

  // #866 K49: the tree must agree with the server's gate, which is read per
  // request; a stale client "off" paired the legacy tree with a backend that
  // delegates its calls to the loop ("finish the probe first", 409s).
  it("a REMEMBERED 'off' (the flag read failed) is a guess: the probe decides", async () => {
    flagState.value = { flags: { learning_loop: "off" }, ready: true, fresh: false };
    getLoopStatus.mockResolvedValue({ active: true });
    const { result } = renderHook(() => useLoopStatus("u1", true));
    expect(result.current.status).toBeNull();
    await act(async () => { await Promise.resolve(); });
    expect(getLoopStatus).toHaveBeenCalledTimes(1);
    expect(result.current.status).toBe(true);
  });

  it("recheck() with a fresh 'off' probes in the background: legacy meanwhile, the loop once it is on", async () => {
    flagState.value = { flags: { learning_loop: "off" }, ready: true, fresh: true };
    let answer: (v: { active: boolean }) => void = () => {};
    getLoopStatus.mockImplementation(() => new Promise((r) => { answer = r; }));
    const { result } = renderHook(() => useLoopStatus("u1", true));
    expect(result.current.status).toBe(false);
    expect(getLoopStatus).not.toHaveBeenCalled();
    act(() => { result.current.recheck(); });
    expect(getLoopStatus).toHaveBeenCalledTimes(1);
    expect(result.current.status).toBe(false); // the legacy tree stays mounted while it asks
    await act(async () => { answer({ active: true }); });
    expect(result.current.status).toBe(true);
  });

  it("recheck() that finds the loop off, or cannot ask, leaves the legacy tree alone", async () => {
    flagState.value = { flags: { learning_loop: "off" }, ready: true, fresh: true };
    getLoopStatus.mockResolvedValueOnce({ active: false }).mockRejectedValueOnce(new Error("down"));
    const { result } = renderHook(() => useLoopStatus("u1", true));
    await act(async () => { result.current.recheck(); });
    await act(async () => { result.current.recheck(); });
    expect(getLoopStatus).toHaveBeenCalledTimes(2);
    expect(result.current.status).toBe(false);
  });

  it("the hand-over holds until a newer flag read says off", async () => {
    flagState.value = { flags: { learning_loop: "off" }, ready: true, fresh: true };
    getLoopStatus.mockResolvedValueOnce({ active: true }).mockImplementation(never);
    const { result, rerender } = renderHook(() => useLoopStatus("u1", true));
    await act(async () => { result.current.recheck(); });
    expect(result.current.status).toBe(true);
    // the next minute's read agrees: still the loop while its own probe is in
    // flight, so the page never drops to "Loading…" (no remount)
    flagState.value = { flags: { learning_loop: "on" }, ready: true, fresh: true };
    rerender();
    expect(result.current.status).toBe(true);
    // the owner turned it off again: the newer read decides
    flagState.value = { flags: { learning_loop: "off" }, ready: true, fresh: true };
    rerender();
    expect(result.current.status).toBe(false);
  });

  it("a recheck answered for another user never applies", async () => {
    flagState.value = { flags: { learning_loop: "off" }, ready: true, fresh: true };
    let answer: (v: { active: boolean }) => void = () => {};
    getLoopStatus.mockImplementation(() => new Promise((r) => { answer = r; }));
    const { result, rerender } = renderHook(({ user }) => useLoopStatus(user, true), { initialProps: { user: "u1" } });
    act(() => { result.current.recheck(); });
    rerender({ user: "u2" });
    await act(async () => { answer({ active: true }); });
    expect(result.current.status).toBe(false);
  });
});
