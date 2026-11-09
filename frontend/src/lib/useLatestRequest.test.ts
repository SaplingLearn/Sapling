// @vitest-environment jsdom
/**
 * useLatestRequest (#769) — the shared "latest request wins" token.
 */
import { describe, it, expect, afterEach } from "vitest";
import { renderHook, cleanup } from "@testing-library/react";
import { useLatestRequest } from "./useLatestRequest";

afterEach(cleanup);

describe("useLatestRequest", () => {
  it("a fresh token is current", () => {
    const { result } = renderHook(() => useLatestRequest());
    expect(result.current.begin().isCurrent()).toBe(true);
  });

  it("begin() supersedes every earlier token", () => {
    const { result } = renderHook(() => useLatestRequest());
    const a = result.current.begin();
    const b = result.current.begin();
    expect(a.isCurrent()).toBe(false);
    expect(b.isCurrent()).toBe(true);
  });

  it("cancel() invalidates outstanding tokens without starting a new one", () => {
    const { result } = renderHook(() => useLatestRequest());
    const a = result.current.begin();
    result.current.cancel();
    expect(a.isCurrent()).toBe(false);
    expect(result.current.begin().isCurrent()).toBe(true);
  });

  it("unmount cancels in-flight tokens", () => {
    const { result, unmount } = renderHook(() => useLatestRequest());
    const a = result.current.begin();
    unmount();
    expect(a.isCurrent()).toBe(false);
  });

  it("is referentially stable across renders (safe in effect deps)", () => {
    const { result, rerender } = renderHook(() => useLatestRequest());
    const first = result.current;
    rerender();
    expect(result.current).toBe(first);
  });

  it("separate hooks are independent slots", () => {
    const { result } = renderHook(() => ({ x: useLatestRequest(), y: useLatestRequest() }));
    const a = result.current.x.begin();
    result.current.y.begin();
    expect(a.isCurrent()).toBe(true);
  });
});
