// @vitest-environment jsdom
/**
 * `useIsMobile` is read by `ShellFrame` to pick the whole app shell (SideNav
 * vs TopNav), so getting it wrong is either a hydration error or a layout
 * snap. These tests pin the two halves of that contract (#110):
 *
 *   1. SSR and the hydrating render both report *desktop*, whatever the real
 *      viewport is — otherwise React 19 reports a recoverable hydration error.
 *   2. Once hydrated, the hook tracks `matchMedia` and updates on change.
 *
 * They also pin the breakpoint string itself: the `@media (max-width: 767px)`
 * rules in globals.css that cover the pre-hydration paint are only correct as
 * long as the hook queries the same width.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act } from "react";
import { renderToString } from "react-dom/server";
import { hydrateRoot, type Root } from "react-dom/client";

import {
  useIsMobile,
  MOBILE_BREAKPOINT,
  __resetMediaStoresForTests,
} from "./useIsMobile";

/** `act` requires this flag; it isn't in the ambient global types. */
const actEnv = globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean };

function Probe() {
  return <div>{useIsMobile() ? "mobile" : "desktop"}</div>;
}

/** Controllable `window.matchMedia` — jsdom's own stub is permanently false. */
function installMatchMedia(initiallyMatches: boolean) {
  const listeners = new Set<() => void>();
  const mql = {
    matches: initiallyMatches,
    media: "",
    addEventListener: (_type: string, cb: () => void) => { listeners.add(cb); },
    removeEventListener: (_type: string, cb: () => void) => { listeners.delete(cb); },
  };
  const matchMedia = vi.fn(() => mql);
  window.matchMedia = matchMedia as unknown as typeof window.matchMedia;
  return {
    matchMedia,
    listenerCount: () => listeners.size,
    set(next: boolean) {
      mql.matches = next;
      listeners.forEach(cb => cb());
    },
  };
}

let container: HTMLDivElement;
let root: Root | null = null;

beforeEach(() => {
  actEnv.IS_REACT_ACT_ENVIRONMENT = true;
  __resetMediaStoresForTests();
  container = document.createElement("div");
  document.body.appendChild(container);
});

afterEach(() => {
  if (root) act(() => root!.unmount());
  root = null;
  container.remove();
  actEnv.IS_REACT_ACT_ENVIRONMENT = undefined;
});

/** SSR the probe into `container`, then hydrate it. Returns recoverable errors. */
async function ssrThenHydrate(): Promise<unknown[]> {
  container.innerHTML = renderToString(<Probe />);
  const recoverable: unknown[] = [];
  await act(async () => {
    root = hydrateRoot(container, <Probe />, {
      onRecoverableError: (err) => recoverable.push(err),
    });
  });
  return recoverable;
}

describe("useIsMobile — SSR safety", () => {
  it("renders the desktop branch on the server even on a mobile viewport", () => {
    installMatchMedia(true);
    expect(renderToString(<Probe />)).toContain("desktop");
  });

  it("hydrates a mobile viewport without a recoverable error", async () => {
    installMatchMedia(true);
    const recoverable = await ssrThenHydrate();
    expect(recoverable).toEqual([]);
  });

  it("switches to the mobile value once hydration commits", async () => {
    installMatchMedia(true);
    await ssrThenHydrate();
    expect(container.textContent).toBe("mobile");
  });

  it("leaves a desktop viewport on the desktop value", async () => {
    installMatchMedia(false);
    const recoverable = await ssrThenHydrate();
    expect(recoverable).toEqual([]);
    expect(container.textContent).toBe("desktop");
  });
});

describe("useIsMobile — subscription", () => {
  it("tracks later media-query changes", async () => {
    const mm = installMatchMedia(false);
    await ssrThenHydrate();
    expect(container.textContent).toBe("desktop");

    await act(async () => { mm.set(true); });
    expect(container.textContent).toBe("mobile");

    await act(async () => { mm.set(false); });
    expect(container.textContent).toBe("desktop");
  });

  it("shares one MediaQueryList across consumers and doesn't resubscribe", async () => {
    const mm = installMatchMedia(false);
    const tree = <div><Probe /><Probe /><Probe /></div>;
    container.innerHTML = renderToString(tree);
    await act(async () => { root = hydrateRoot(container, tree); });

    expect(mm.matchMedia).toHaveBeenCalledTimes(1);
    // React subscribes once per hook instance; what the store cache buys is a
    // stable `subscribe` identity, so re-renders don't churn listeners.
    expect(mm.listenerCount()).toBe(3);

    await act(async () => { mm.set(true); });
    expect(container.textContent).toBe("mobilemobilemobile");
    expect(mm.matchMedia).toHaveBeenCalledTimes(1);
    expect(mm.listenerCount()).toBe(3);
  });

  it("queries the same width the globals.css mobile rules use", async () => {
    const mm = installMatchMedia(false);
    await ssrThenHydrate();
    expect(mm.matchMedia).toHaveBeenCalledWith(
      `(max-width: ${MOBILE_BREAKPOINT - 1}px)`,
    );
    expect(MOBILE_BREAKPOINT).toBe(768);
  });
});
