// @vitest-environment jsdom
/** The reader tells its stylesheet how tall the sticky top bar really is. */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";
import React from "react";

import { useBarHeight } from "./useBarHeight";

function Page() {
  const page = React.useRef<HTMLDivElement>(null);
  useBarHeight(page);
  return (
    <div ref={page} data-testid="page">
      <header>Study</header>
      <article>
        <header>The guide&apos;s own header</header>
      </article>
    </div>
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("useBarHeight", () => {
  it("sets --guide-bar from the top bar, again each time the bar changes height", () => {
    const observed: Element[] = [];
    let resized = () => {};
    const disconnect = vi.fn();
    vi.stubGlobal(
      "ResizeObserver",
      class {
        constructor(callback: () => void) {
          resized = callback;
        }
        observe(el: Element) {
          observed.push(el);
        }
        disconnect = disconnect;
      },
    );
    const { getByTestId, unmount } = render(<Page />);
    const page = getByTestId("page");
    const bar = page.querySelector("header") as HTMLElement;
    // The page's own bar, not the article's header further down.
    expect(observed).toEqual([bar]);

    // One row of actions, then two on a phone.
    Object.defineProperty(bar, "offsetHeight", { configurable: true, value: 80 });
    resized();
    expect(page.style.getPropertyValue("--guide-bar")).toBe("80px");
    Object.defineProperty(bar, "offsetHeight", { configurable: true, value: 128 });
    resized();
    expect(page.style.getPropertyValue("--guide-bar")).toBe("128px");

    unmount();
    expect(disconnect).toHaveBeenCalledTimes(1);
  });

  it("leaves the stylesheet's own height in place where nothing can measure", () => {
    vi.stubGlobal("ResizeObserver", undefined);
    const { getByTestId } = render(<Page />);
    expect(getByTestId("page").style.getPropertyValue("--guide-bar")).toBe("");
  });
});
