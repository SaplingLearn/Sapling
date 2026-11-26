// Extends Vitest's `expect` with the @testing-library/jest-dom matchers
// (.toBeInTheDocument, .toHaveTextContent, .toHaveAttribute, etc.).
// Loaded only for tests that opt into a DOM via // @vitest-environment jsdom;
// the matchers themselves are no-ops when there's no document.
import "@testing-library/jest-dom/vitest";

// jsdom 29 under Vitest exposes no `window.localStorage` (it is simply
// undefined, even at a non-opaque origin), so components that persist prefs
// there — useLayoutPref, useActiveSemester — explode in DOM tests. Install a
// plain in-memory Storage per test file when the environment has a window but
// no localStorage. Real browsers are unaffected; node-env tests skip this.
if (typeof window !== "undefined" && !window.localStorage) {
  const store = new Map<string, string>();
  const localStorageShim: Storage = {
    get length() {
      return store.size;
    },
    key: (i: number) => Array.from(store.keys())[i] ?? null,
    getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
    setItem: (k: string, v: string) => void store.set(String(k), String(v)),
    removeItem: (k: string) => void store.delete(k),
    clear: () => store.clear(),
  };
  Object.defineProperty(window, "localStorage", {
    value: localStorageShim,
    configurable: true,
  });
}

// jsdom ships no `window.matchMedia` at all, so any component that reads
// `window.matchMedia('(prefers-reduced-motion: reduce)').matches` (the
// landing knowledge-graph demo, KnowledgeGraph3D, ...) would throw under
// vitest without a stub. Default to reduced-motion = true: that's the
// parked/complete frame, which is also the correct assertion target for a
// hermetic unit test (no RAF loop, no clock-driven flakiness). Test files
// that need different behavior (e.g. `useIsMobile.test.tsx`,
// `KnowledgeGraph3D.test.tsx`) already install their own `window.matchMedia`
// per test via `beforeEach`, which overrides this file-load-time default.
if (typeof window !== "undefined" && typeof window.matchMedia !== "function") {
  window.matchMedia = ((query: string) => ({
    matches: query.includes("prefers-reduced-motion"),
    media: query,
    onchange: null,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
    dispatchEvent() {
      return false;
    },
  })) as unknown as typeof window.matchMedia;
}

// Radix primitives (components/ui Menu, Popover, Tooltip) position with
// ResizeObserver and use pointer capture; jsdom has neither.
if (typeof window !== "undefined") {
  if (!("ResizeObserver" in window)) {
    class ResizeObserverShim {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
    (window as unknown as { ResizeObserver: unknown }).ResizeObserver = ResizeObserverShim;
    (globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = ResizeObserverShim;
  }
  const proto = window.HTMLElement.prototype as unknown as Record<string, unknown>;
  if (!proto.hasPointerCapture) proto.hasPointerCapture = () => false;
  if (!proto.setPointerCapture) proto.setPointerCapture = () => {};
  if (!proto.releasePointerCapture) proto.releasePointerCapture = () => {};
}

// toHaveTwStyle: toHaveStyle for the Tailwind era. jsdom applies no
// stylesheet, so a declaration that moved from an inline style to a class is
// invisible to toHaveStyle. This compares against what the element's classes
// and inline style set together (src/test-utils/twStyle.ts).
import { expect as vitestExpect } from "vitest";
import { cssValue, kebab, toClasses } from "./scripts/codemods/css-to-tailwind.mjs";
import { twStyle } from "./src/test-utils/twStyle";

vitestExpect.extend({
  toHaveTwStyle(received: Element, expected: Record<string, string | number>) {
    const actual = twStyle(received);
    const misses: string[] = [];
    for (const [prop, raw] of Object.entries(expected)) {
      const camel = prop.includes("-") && !prop.startsWith("--") ? prop.replace(/-([a-z])/g, (_, c: string) => c.toUpperCase()) : prop;
      const name = kebab(camel);
      const probe = document.createElement("div");
      probe.style.setProperty(name, cssValue(camel, raw));
      // Compare longhand by longhand: a shorthand like border-top only
      // reads back whole when every part was set the same way.
      const parts = probe.style.length ? Array.from({ length: probe.style.length }, (_, i) => probe.style[i]) : [name];
      const partMisses = parts
        .filter((part) => actual.getPropertyValue(part) !== probe.style.getPropertyValue(part))
        .map((part) => `${part}: wanted "${probe.style.getPropertyValue(part)}", got "${actual.getPropertyValue(part)}"`);
      if (!partMisses.length) continue;
      // jsdom can't split a shorthand holding var() into longhands; accept
      // the exact classes the codemod writes for that declaration.
      const classes = (received.getAttribute("class") ?? "").split(/\s+/);
      const forms = [toClasses(camel, raw), toClasses(camel, raw, { strict: true })];
      if (forms.some((f) => f.length > 0 && f.every((c: string) => classes.includes(c)))) continue;
      misses.push(...partMisses);
    }
    return {
      pass: misses.length === 0,
      message: () =>
        misses.length
          ? `expected element to have\n  ${misses.join("\n  ")}\nclass="${received.getAttribute("class") ?? ""}"`
          : `expected element not to have ${JSON.stringify(expected)}`,
    };
  },
});
