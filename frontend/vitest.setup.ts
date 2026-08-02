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
