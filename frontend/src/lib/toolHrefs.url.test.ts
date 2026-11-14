// @vitest-environment jsdom
/**
 * The URL edits the Study tools make in place (`start` acted on, a review or
 * the builder marked): the address bar changes AND the router is told.
 *
 * "Told" is the state argument. Next patches `history.pushState` /
 * `replaceState` and syncs `useSearchParams` from them, but skips its hook for
 * a state carrying `__NA` (the state it wrote itself). Passing
 * `window.history.state` therefore moves the address bar and leaves the router
 * on the old URL; passing null is what reaches it. jsdom has no router, so
 * what can be pinned here is the argument.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { consumeStartParam, editUrlInPlace, startStillRequested } from "./toolHrefs";

/** A real App Router entry's state. Without `__NA` on the entry, "null" and
 *  "the state that was there" could not be told apart below. */
const NEXT_STATE = { __NA: true, __PRIVATE_NEXTJS_INTERNALS_TREE: ["flashcards"] };

let calls: { via: "push" | "replace"; state: unknown }[];

function arriveAt(pathAndQuery: string) {
  window.history.replaceState(NEXT_STATE, "", pathAndQuery);
}

beforeEach(() => {
  arriveAt("/flashcards?course=c1&concepts=Recursion&start=1");
  calls = [];
  const realPush = window.history.pushState.bind(window.history);
  const realReplace = window.history.replaceState.bind(window.history);
  vi.spyOn(window.history, "pushState").mockImplementation((state, unused, url) => {
    calls.push({ via: "push", state });
    return realPush(state, unused, url);
  });
  vi.spyOn(window.history, "replaceState").mockImplementation((state, unused, url) => {
    calls.push({ via: "replace", state });
    return realReplace(state, unused, url);
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  window.history.replaceState(null, "", "/");
});

describe("consumeStartParam", () => {
  it("drops `start`, keeps the rest of the link, and tells the router", () => {
    expect(startStillRequested()).toBe(true);
    consumeStartParam();

    expect(window.location.pathname + window.location.search).toBe("/flashcards?course=c1&concepts=Recursion");
    expect(startStillRequested()).toBe(false);
    // Rewritten in place (no new entry), with a null state: the entry's own
    // state (`__NA`) would make Next skip the sync and keep `start=1`.
    expect(calls).toEqual([{ via: "replace", state: null }]);
  });

  it("leaves a URL that does not ask to start alone", () => {
    arriveAt("/flashcards?course=c1");
    calls = [];
    consumeStartParam();

    expect(window.location.search).toBe("?course=c1");
    expect(calls).toEqual([]);
  });
});

describe("editUrlInPlace", () => {
  const withReview = () => {
    const url = new URL(window.location.href);
    url.searchParams.set("review", "1");
    return url;
  };

  it("rewrites the current entry by default", () => {
    const entries = window.history.length;
    editUrlInPlace(withReview());

    expect(window.location.search).toBe("?course=c1&concepts=Recursion&start=1&review=1");
    expect(window.history.length).toBe(entries);
    expect(calls).toEqual([{ via: "replace", state: null }]);
  });

  it("adds an entry when asked to push, so Back undoes the edit", () => {
    const entries = window.history.length;
    editUrlInPlace(withReview(), "push");

    expect(window.location.search).toBe("?course=c1&concepts=Recursion&start=1&review=1");
    expect(window.history.length).toBe(entries + 1);
    expect(calls).toEqual([{ via: "push", state: null }]);
  });
});
