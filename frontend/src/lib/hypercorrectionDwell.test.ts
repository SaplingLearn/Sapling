// @vitest-environment jsdom
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { type DwellArm, dwellArm, feedbackDwellLocked, useHypercorrectionDwell } from "./hypercorrectionDwell";

describe("feedbackDwellLocked", () => {
  it("locks only while a positive dwell window is open", () => {
    expect(feedbackDwellLocked(null, 0, 0)).toBe(false);
    expect(feedbackDwellLocked(0, 0, 0)).toBe(false);
    expect(feedbackDwellLocked(8000, 1000, 1000)).toBe(true);
    expect(feedbackDwellLocked(8000, 1000, 8999)).toBe(true);
    expect(feedbackDwellLocked(8000, 1000, 9000)).toBe(false);
  });
});

describe("useHypercorrectionDwell", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("holds until feedback_dwell_ms elapses, then unlocks", () => {
    const { result, rerender } = renderHook(
      ({ ms }: { ms: number | null }) => useHypercorrectionDwell(ms),
      { initialProps: { ms: 8000 as number | null } },
    );
    expect(result.current).toBe(true);
    act(() => {
      vi.advanceTimersByTime(7999);
    });
    expect(result.current).toBe(true);
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(result.current).toBe(false);

    rerender({ ms: null });
    expect(result.current).toBe(false);
  });

  it("a new positive value re-arms the hold; null clears it at once", () => {
    const { result, rerender } = renderHook(
      ({ ms }: { ms: number | null }) => useHypercorrectionDwell(ms),
      { initialProps: { ms: 8000 as number | null } },
    );
    act(() => {
      vi.advanceTimersByTime(8000);
    });
    expect(result.current).toBe(false);
    rerender({ ms: 5000 });
    expect(result.current).toBe(true);
    rerender({ ms: null });
    expect(result.current).toBe(false);
    rerender({ ms: 5000 });
    expect(result.current).toBe(true);
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(result.current).toBe(false);
  });

  it("zero or null never locks", () => {
    const { result, rerender } = renderHook(
      ({ ms }: { ms: number | null | undefined }) => useHypercorrectionDwell(ms),
      { initialProps: { ms: 0 as number | null | undefined } },
    );
    expect(result.current).toBe(false);
    rerender({ ms: undefined });
    expect(result.current).toBe(false);
  });

  it("re-arms on a second grade with the same duration (a fresh arm)", () => {
    vi.useFakeTimers();
    const { result, rerender } = renderHook(
      ({ arm }: { arm: DwellArm }) => useHypercorrectionDwell(arm),
      { initialProps: { arm: dwellArm(8000) } },
    );
    expect(result.current).toBe(true);
    act(() => { vi.advanceTimersByTime(8000); });
    expect(result.current).toBe(false);
    rerender({ arm: dwellArm(8000) });
    expect(result.current).toBe(true);
    act(() => { vi.advanceTimersByTime(7999); });
    expect(result.current).toBe(true);
    act(() => { vi.advanceTimersByTime(1); });
    expect(result.current).toBe(false);
    vi.useRealTimers();
  });
});
