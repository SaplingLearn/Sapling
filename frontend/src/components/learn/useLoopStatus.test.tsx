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
const flagState = vi.hoisted(() => ({ value: { flags: { learning_loop: "on" } as Record<string, string>, ready: true } }));
vi.mock("@/context/FlagsContext", () => ({ useFlagMap: () => flagState.value }));

import {
  LOOP_STATUS_REUSE_MS,
  LOOP_STATUS_TIMEOUT_MS,
  __resetLoopStatusMemoForTests,
  useLoopStatus,
} from "./useLoopStatus";

const never = () => new Promise<{ active: boolean }>(() => {});

beforeEach(() => {
  vi.useFakeTimers();
  getLoopStatus.mockReset();
  __resetLoopStatusMemoForTests();
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

  it("a screen that reuses asks nothing when a recent probe answered, and is resolved from its first render (#866 K46)", async () => {
    getLoopStatus.mockResolvedValue({ active: true });
    const learn = renderHook(() => useLoopStatus("u1", true));
    await act(async () => { await Promise.resolve(); });
    expect(learn.result.current.status).toBe(true);
    learn.unmount();
    const quiz = renderHook(() => useLoopStatus("u1", true, { reuse: true }));
    expect(quiz.result.current.status).toBe(true);
    await act(async () => { await vi.advanceTimersByTimeAsync(LOOP_STATUS_TIMEOUT_MS * 2); });
    expect(getLoopStatus).toHaveBeenCalledTimes(1);
  });

  it("an old answer, another student's, or a screen that does not reuse, probes", async () => {
    getLoopStatus.mockResolvedValue({ active: false });
    renderHook(() => useLoopStatus("u1", true)).unmount();
    await act(async () => { await Promise.resolve(); });
    renderHook(() => useLoopStatus("u1", true));  // Learn always probes
    renderHook(() => useLoopStatus("u2", true, { reuse: true }));
    await act(async () => { await Promise.resolve(); });
    expect(getLoopStatus).toHaveBeenCalledTimes(3);
    await act(async () => { await vi.advanceTimersByTimeAsync(LOOP_STATUS_REUSE_MS); });
    const stale = renderHook(() => useLoopStatus("u1", true, { reuse: true }));
    expect(stale.result.current.status).toBeNull();
    await act(async () => { await Promise.resolve(); });
    expect(getLoopStatus).toHaveBeenCalledTimes(4);
    expect(stale.result.current.status).toBe(false);
  });

  it("a reused answer never outranks a flag that says off", async () => {
    getLoopStatus.mockResolvedValue({ active: true });
    renderHook(() => useLoopStatus("u1", true)).unmount();
    await act(async () => { await Promise.resolve(); });
    flagState.value = { flags: { learning_loop: "off" }, ready: true };
    const { result } = renderHook(() => useLoopStatus("u1", true, { reuse: true }));
    expect(result.current.status).toBe(false);
  });
});
