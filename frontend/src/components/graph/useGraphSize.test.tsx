// @vitest-environment jsdom
/**
 * `useGraphSize`: a graph is handed its real size before it is first drawn.
 *
 * The screens used to start from a guessed size and correct it from a
 * ResizeObserver, which reports after a paint: the graph laid its courses
 * out for the guess, then visibly re-laid them out a frame later. The hook
 * measures the element as it attaches, in the commit, and is `null` until
 * then, so a graph rendered only once the size is known opens at it.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render } from "@testing-library/react";
import React from "react";
import { type GraphSize, useGraphSize } from "./useGraphSize";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

/** A ResizeObserver whose reports the test sends. */
function fakeResizeObserver() {
  const observers: Array<(width: number, height: number) => void> = [];
  vi.stubGlobal(
    "ResizeObserver",
    class {
      private cb: ResizeObserverCallback;
      constructor(cb: ResizeObserverCallback) {
        this.cb = cb;
      }
      observe() {
        observers.push((width, height) =>
          this.cb([{ contentRect: { width, height } } as ResizeObserverEntry], this as unknown as ResizeObserver),
        );
      }
      disconnect() {}
      unobserve() {}
    },
  );
  return (width: number, height: number) => act(() => observers.forEach((report) => report(width, height)));
}

function layoutSize(width: number, height: number) {
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(width);
  vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(height);
}

function Probe({ seen }: { seen: Array<GraphSize | null> }) {
  const [ref, size] = useGraphSize<HTMLDivElement>({ w: 720, h: 420 });
  seen.push(size);
  return <div ref={ref} style={{ padding: "3px 5px" }} />;
}

describe("useGraphSize", () => {
  it("measures the element's content box as it mounts, so nothing is drawn at a guess", () => {
    fakeResizeObserver();
    layoutSize(510, 706);
    const seen: Array<GraphSize | null> = [];
    render(<Probe seen={seen} />);
    // Unknown on the first render, then the real size before render() returns
    // (in the browser: before the first paint). Never the 720 × 420 guess.
    expect(seen[0]).toBeNull();
    expect(seen.at(-1)).toEqual({ w: 500, h: 700 });
    expect(seen).not.toContainEqual({ w: 720, h: 420 });
  });

  it("stands in the fallback where nothing can be measured", () => {
    fakeResizeObserver();
    layoutSize(0, 0);
    const seen: Array<GraphSize | null> = [];
    render(<Probe seen={seen} />);
    expect(seen.at(-1)).toEqual({ w: 720, h: 420 });
  });

  it("follows the element's resizes, but not a re-measure within a pixel", () => {
    const report = fakeResizeObserver();
    layoutSize(510, 706);
    const seen: Array<GraphSize | null> = [];
    render(<Probe seen={seen} />);
    const first = seen.at(-1);
    report(500.4, 699.7);
    expect(seen.at(-1)).toBe(first);
    report(480, 700);
    expect(seen.at(-1)).toEqual({ w: 480, h: 700 });
  });
});
