/**
 * One IntersectionObserver for every scroll-triggered animation on the page.
 *
 * The landing page reveals a few dozen blocks. Giving each its own observer
 * would work, but one shared instance with an element → callback map costs a
 * single registration in the browser's intersection bookkeeping instead of
 * dozens, and it keeps the threshold in one place. The threshold matches the
 * `[data-reveal]` scan this replaced, so nothing changes about *when* a block
 * arrives — only what schedules it.
 *
 * Every reveal is one-shot: the callback runs on the first intersecting entry
 * and the element is dropped from the map and unobserved in the same breath.
 * Nothing re-hides on the way back up, which is the same rule the acts follow.
 */

/** Matches the `[data-reveal]` scan that preceded this. */
const THRESHOLD = 0.12;

let observer: IntersectionObserver | null = null;
const callbacks = new Map<Element, () => void>();

function hasObserver(): boolean {
  return typeof IntersectionObserver !== 'undefined';
}

function ensure(): IntersectionObserver | null {
  if (!hasObserver()) return null;
  if (!observer) {
    observer = new IntersectionObserver(
      (entries) => {
        for (const en of entries) {
          if (!en.isIntersecting) continue;
          const cb = callbacks.get(en.target);
          if (!cb) continue;
          // drop it before calling: the callback renders, and a re-entrant
          // entry for the same element must not fire it twice
          callbacks.delete(en.target);
          observer?.unobserve(en.target);
          cb();
        }
      },
      { threshold: THRESHOLD },
    );
  }
  return observer;
}

/**
 * Run `cb` once, the first time `el` is at least {@link THRESHOLD} visible.
 *
 * Fires `cb` synchronously and returns a no-op when the browser has no
 * IntersectionObserver. Callers rely on that: it is what keeps content
 * visible rather than stranded at `opacity:0` in environments that cannot
 * tell them when it came into view.
 *
 * @returns an unsubscribe for the not-yet-fired case, safe to call twice.
 */
export function observeOnce(el: Element, cb: () => void): () => void {
  const io = ensure();
  if (!io) {
    cb();
    return () => {};
  }
  callbacks.set(el, cb);
  io.observe(el);
  return () => {
    callbacks.delete(el);
    io.unobserve(el);
  };
}

/** True when the reader has asked the OS for less animation. */
export function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/**
 * Drop the shared observer.
 *
 * Test-only. The instance is module state, so a suite that stubs a fake
 * IntersectionObserver would otherwise keep whichever fake the first test
 * installed for the rest of the file.
 */
export function __resetObserverForTests(): void {
  observer = null;
  callbacks.clear();
}
