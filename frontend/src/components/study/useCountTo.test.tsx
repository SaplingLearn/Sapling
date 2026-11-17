// @vitest-environment jsdom
/**
 * useCountTo on a hand-cranked clock: `frame(ms)` runs the pending animation
 * frame as if `ms` had passed since the page loaded.
 */
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import { HUB_SWITCH_MS, countAt } from "./hubMotion";
import { useCountTo } from "./useCountTo";

function Figure({ value }: { value: number }) {
  return <span data-testid="n">{useCountTo(value)}</span>;
}

let reduced: boolean;
let pending: Map<number, FrameRequestCallback>;
const realMatchMedia = window.matchMedia;
const shown = () => Number(screen.getByTestId("n").textContent);
/** Runs the frame that is waiting, at `ms` on the clock. */
const frame = (ms: number) => act(() => {
  const due = [...pending.values()];
  pending.clear();
  for (const cb of due) cb(ms);
});

beforeEach(() => {
  reduced = false;
  pending = new Map();
  let id = 0;
  window.matchMedia = ((query: string) => ({ matches: reduced && query.includes("reduce") })) as unknown as typeof window.matchMedia;
  vi.spyOn(performance, "now").mockReturnValue(0);
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => { pending.set(++id, cb); return id; });
  vi.stubGlobal("cancelAnimationFrame", (handle: number) => { pending.delete(handle); });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  window.matchMedia = realMatchMedia;
});

describe("useCountTo", () => {
  it("shows the value as given at first, with no count", () => {
    render(<Figure value={51} />);
    expect(shown()).toBe(51);
    expect(pending.size).toBe(0);
  });

  it("counts from the old value to the new one, and ends exactly on it", () => {
    const { rerender } = render(<Figure value={45} />);
    rerender(<Figure value={78} />);
    // The frame of the change still shows the old number.
    expect(shown()).toBe(45);
    frame(HUB_SWITCH_MS / 4);
    expect(shown()).toBe(countAt(45, 78, HUB_SWITCH_MS / 4));
    expect(shown()).toBeGreaterThan(45);
    expect(shown()).toBeLessThan(78);
    frame(HUB_SWITCH_MS);
    expect(shown()).toBe(78);
    // And it stops asking for frames.
    expect(pending.size).toBe(0);
  });

  it("a new value mid-count starts from the number on screen and ends on the last one given", () => {
    const { rerender } = render(<Figure value={45} />);
    rerender(<Figure value={78} />);
    frame(100);
    const mid = shown();
    expect(mid).toBeGreaterThan(45);
    vi.mocked(performance.now).mockReturnValue(100);
    rerender(<Figure value={20} />);
    // One count is running, not two.
    expect(pending.size).toBe(1);
    expect(shown()).toBe(mid);
    frame(100 + HUB_SWITCH_MS / 4);
    expect(shown()).toBe(countAt(mid, 20, HUB_SWITCH_MS / 4));
    frame(100 + HUB_SWITCH_MS);
    expect(shown()).toBe(20);
    expect(pending.size).toBe(0);
  });

  it("going back to the value it left mid-count ends there", () => {
    const { rerender } = render(<Figure value={45} />);
    rerender(<Figure value={78} />);
    frame(100);
    vi.mocked(performance.now).mockReturnValue(100);
    rerender(<Figure value={45} />);
    frame(100 + HUB_SWITCH_MS);
    expect(shown()).toBe(45);
  });

  it("unmounting stops the count", () => {
    const { rerender, unmount } = render(<Figure value={45} />);
    rerender(<Figure value={78} />);
    expect(pending.size).toBe(1);
    unmount();
    expect(pending.size).toBe(0);
  });

  it("under reduced motion the new value is simply there", () => {
    reduced = true;
    const { rerender } = render(<Figure value={45} />);
    rerender(<Figure value={78} />);
    expect(shown()).toBe(78);
    expect(pending.size).toBe(0);
  });
});
