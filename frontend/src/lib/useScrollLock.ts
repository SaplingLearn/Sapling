import { useEffect } from "react";

/**
 * Scroll-lock for overlays (modals, drawers, lightboxes).
 *
 * Two things this hook gets right that a naive
 * `document.body.style.overflow = "hidden"` does not:
 *
 * 1. **It refcounts per element.** Overlays overlap — `FeedbackFlow` is mounted
 *    globally by `ShellFrame` and auto-opens on a timer, so it can open on top
 *    of (or underneath) any other modal. With naive save/restore, the second
 *    lock captures the first lock's `"hidden"` as its "previous" value, the
 *    first unlock releases the scroll while the second overlay is still up, and
 *    the second unlock restores the stale `"hidden"` — freezing the page until
 *    navigation. Refcounting means only the 0->1 transition captures the
 *    original value and only the 1->0 transition restores it.
 *
 * 2. **It locks the element that actually scrolls.** Inside the app shell,
 *    `<body>` never scrolls: `ShellFrame` roots both layouts at
 *    `height: 100vh; overflow: hidden` and gives `<main>` `flex: 1; overflow-y:
 *    auto`. Locking `<body>` there is a no-op on an element that has no
 *    scrollport. On the pre-auth/marketing pages there is no shell and `<body>`
 *    is the real scroller. So we resolve the target at lock time: the element
 *    the shell tags with `data-scroll-container`, falling back to `<body>`.
 *
 * Only the `overflow-x` / `overflow-y` *longhands* are touched, never the
 * `overflow` shorthand. `ShellFrame` sets `overflow-y: auto` inline via React;
 * writing the shorthand and later restoring it to its previous value (`""`)
 * would remove that inline `overflow-y: auto` outright and leave `<main>`
 * unable to scroll at all. Longhands round-trip exactly.
 */

type LockState = {
  count: number;
  prevOverflowX: string;
  prevOverflowY: string;
};

/**
 * Per-element refcounts. Keyed by element so that locking `<main>` and `<body>`
 * (or two different scroll containers) stay independent — a single shared
 * counter would let a lock on one element hold another element hostage.
 */
const locks = new Map<HTMLElement, LockState>();

/** The element the app shell marks as its scrollport, or `<body>` pre-auth. */
function resolveScrollContainer(): HTMLElement | null {
  if (typeof document === "undefined") return null;
  return (
    document.querySelector<HTMLElement>("[data-scroll-container]") ??
    document.body ??
    null
  );
}

function setOrRemove(el: HTMLElement, prop: string, value: string) {
  if (value) el.style.setProperty(prop, value);
  else el.style.removeProperty(prop);
}

function acquire(el: HTMLElement) {
  const existing = locks.get(el);
  if (existing) {
    existing.count += 1;
    return;
  }
  locks.set(el, {
    count: 1,
    prevOverflowX: el.style.getPropertyValue("overflow-x"),
    prevOverflowY: el.style.getPropertyValue("overflow-y"),
  });
  el.style.setProperty("overflow-x", "hidden");
  el.style.setProperty("overflow-y", "hidden");
}

function release(el: HTMLElement) {
  const state = locks.get(el);
  if (!state) return;
  state.count -= 1;
  if (state.count > 0) return;
  locks.delete(el);
  setOrRemove(el, "overflow-x", state.prevOverflowX);
  setOrRemove(el, "overflow-y", state.prevOverflowY);
}

/**
 * Lock the scrolling container while `active` is true. Safe to call from
 * several overlays at once; the container unlocks when the last one releases.
 */
export function useScrollLock(active: boolean) {
  useEffect(() => {
    if (!active) return;
    const el = resolveScrollContainer();
    if (!el) return;
    acquire(el);
    // Release the same element we locked, even if the DOM changed underneath.
    return () => release(el);
  }, [active]);
}

/** Test-only: drop all refcounts without restoring. Not for app code. */
export function __resetScrollLocksForTests() {
  locks.clear();
}
