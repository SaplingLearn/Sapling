// @vitest-environment jsdom
/**
 * Tests for useScrollLock — the refcounted, correctly-targeted scroll lock
 * behind the shared Dialog and every other overlay (#109).
 *
 * WHAT THESE TESTS CAN PROVE (all of it bookkeeping, which is where the bug was):
 *   1. The lock lands on the shell's scrollport, not <body>, when a shell exists.
 *   2. It falls back to <body> pre-auth, where <body> really is the scroller.
 *   3. Overlapping locks refcount: the container stays locked until the LAST
 *      overlay releases, and the ORIGINAL value comes back — not a stale
 *      "hidden" captured from another lock. This is the freeze from the review.
 *   4. Refcounts are per element, so locking <main> and <body> stay independent.
 *   5. The inline `overflow-y: auto` ShellFrame sets round-trips exactly.
 *
 * WHAT THEY CANNOT PROVE: that the scroll-bleed is actually gone. jsdom has no
 * layout engine — nothing here scrolls, has a scrollport, or paints. That
 * these styles produce a non-scrolling background is a browser-only check.
 */
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { renderHook, cleanup } from "@testing-library/react";
import { useScrollLock, __resetScrollLocksForTests } from "./useScrollLock";

/** Stand up what ShellFrame renders: a 100vh/overflow:hidden root + scrolling <main>. */
function mountShell(): HTMLElement {
  const root = document.createElement("div");
  root.style.setProperty("height", "100vh");
  root.style.setProperty("overflow", "hidden");
  const main = document.createElement("main");
  main.id = "main-content";
  main.setAttribute("data-scroll-container", "");
  // Mirrors ShellFrame's inline style={{ flex: 1, overflowY: "auto" }}.
  main.style.setProperty("flex", "1");
  main.style.setProperty("overflow-y", "auto");
  root.appendChild(main);
  document.body.appendChild(root);
  return main;
}

beforeEach(() => {
  document.body.innerHTML = "";
  document.body.removeAttribute("style");
  __resetScrollLocksForTests();
});

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
  document.body.removeAttribute("style");
  __resetScrollLocksForTests();
});

describe("useScrollLock — targeting", () => {
  it("locks the shell scrollport, not <body>", () => {
    const main = mountShell();

    renderHook(() => useScrollLock(true));

    expect(main.style.getPropertyValue("overflow-y")).toBe("hidden");
    // The whole point of the retarget: <body> never scrolls inside the shell,
    // so locking it (what the old hook did) was a no-op on the wrong element.
    expect(document.body.style.getPropertyValue("overflow-y")).toBe("");
  });

  it("falls back to <body> when there is no shell (pre-auth/landing)", () => {
    const { unmount } = renderHook(() => useScrollLock(true));

    expect(document.body.style.getPropertyValue("overflow-y")).toBe("hidden");
    expect(document.body.style.getPropertyValue("overflow-x")).toBe("hidden");

    unmount();
    expect(document.body.style.getPropertyValue("overflow-y")).toBe("");
  });

  it("does nothing while inactive", () => {
    const main = mountShell();

    renderHook(() => useScrollLock(false));

    expect(main.style.getPropertyValue("overflow-y")).toBe("auto");
    expect(document.body.getAttribute("style")).toBeNull();
  });
});

describe("useScrollLock — refcounting", () => {
  it("stays locked until the last overlay releases, then restores the original", () => {
    const main = mountShell();

    // Two overlapping overlays — e.g. FeedbackFlow auto-opening on its 45s
    // timer on top of an already-open FlashcardImportModal.
    const first = renderHook(() => useScrollLock(true));
    const second = renderHook(() => useScrollLock(true));
    expect(main.style.getPropertyValue("overflow-y")).toBe("hidden");

    // The naive hook released the lock here, while the second overlay was up.
    first.unmount();
    expect(main.style.getPropertyValue("overflow-y")).toBe("hidden");

    // ...and then restored a stale "hidden" here, freezing the page.
    second.unmount();
    expect(main.style.getPropertyValue("overflow-y")).toBe("auto");
  });

  it("restores correctly when overlays close in reverse order", () => {
    const main = mountShell();

    const first = renderHook(() => useScrollLock(true));
    const second = renderHook(() => useScrollLock(true));

    second.unmount();
    expect(main.style.getPropertyValue("overflow-y")).toBe("hidden");

    first.unmount();
    expect(main.style.getPropertyValue("overflow-y")).toBe("auto");
  });

  it("handles a false -> true -> false transition without capturing a stale value", () => {
    const main = mountShell();

    // A lock already held by another overlay when this one turns on.
    const held = renderHook(() => useScrollLock(true));

    const toggled = renderHook(
      ({ active }: { active: boolean }) => useScrollLock(active),
      { initialProps: { active: false } },
    );

    toggled.rerender({ active: true });
    expect(main.style.getPropertyValue("overflow-y")).toBe("hidden");

    toggled.rerender({ active: false });
    // Still held by the other overlay.
    expect(main.style.getPropertyValue("overflow-y")).toBe("hidden");

    held.unmount();
    expect(main.style.getPropertyValue("overflow-y")).toBe("auto");

    toggled.unmount();
    expect(main.style.getPropertyValue("overflow-y")).toBe("auto");
  });

  it("releases when a still-active overlay unmounts", () => {
    const main = mountShell();

    const { unmount } = renderHook(() => useScrollLock(true));
    expect(main.style.getPropertyValue("overflow-y")).toBe("hidden");

    unmount();
    expect(main.style.getPropertyValue("overflow-y")).toBe("auto");
  });

  it("survives three overlapping locks", () => {
    const main = mountShell();

    const hooks = [
      renderHook(() => useScrollLock(true)),
      renderHook(() => useScrollLock(true)),
      renderHook(() => useScrollLock(true)),
    ];
    expect(main.style.getPropertyValue("overflow-y")).toBe("hidden");

    hooks[1].unmount();
    hooks[0].unmount();
    expect(main.style.getPropertyValue("overflow-y")).toBe("hidden");

    hooks[2].unmount();
    expect(main.style.getPropertyValue("overflow-y")).toBe("auto");
  });
});

describe("useScrollLock — per-element isolation", () => {
  it("keeps <body> and <main> refcounts independent", () => {
    // Lock <body> first, pre-auth style (no shell in the DOM yet).
    const bodyLock = renderHook(() => useScrollLock(true));
    expect(document.body.style.getPropertyValue("overflow-y")).toBe("hidden");

    // Now a shell appears; the next lock resolves to <main>.
    const main = mountShell();
    const mainLock = renderHook(() => useScrollLock(true));
    expect(main.style.getPropertyValue("overflow-y")).toBe("hidden");

    // Releasing <main> must not disturb the independent <body> lock.
    // A single shared counter would still be at 1 here and leave <main> locked.
    mainLock.unmount();
    expect(main.style.getPropertyValue("overflow-y")).toBe("auto");
    expect(document.body.style.getPropertyValue("overflow-y")).toBe("hidden");

    bodyLock.unmount();
    expect(document.body.style.getPropertyValue("overflow-y")).toBe("");
  });
});

describe("useScrollLock — style round-tripping", () => {
  it("restores ShellFrame's inline overflow-y:auto exactly", () => {
    const main = mountShell();
    const before = main.getAttribute("style");
    const flexBefore = main.style.getPropertyValue("flex");

    const { unmount } = renderHook(() => useScrollLock(true));
    unmount();

    // Regression guard: writing the `overflow` *shorthand* and restoring it to
    // its previous value ("") would delete ShellFrame's inline overflow-y:auto
    // outright, leaving <main> unable to scroll at all after a modal closes.
    expect(main.getAttribute("style")).toBe(before);
    expect(main.style.getPropertyValue("overflow-y")).toBe("auto");
    // Unrelated inline properties are left alone.
    expect(main.style.getPropertyValue("flex")).toBe(flexBefore);
  });

  it("leaves no residue on an element that had no inline overflow", () => {
    const { unmount } = renderHook(() => useScrollLock(true));
    unmount();

    expect(document.body.style.getPropertyValue("overflow-x")).toBe("");
    expect(document.body.style.getPropertyValue("overflow-y")).toBe("");
    expect(document.body.style.cssText).toBe("");
  });
});
