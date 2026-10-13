/**
 * A speed limit for the wheel.
 *
 * This landing is scroll-scrubbed: each act is pinned to a fixed runway of
 * document height, so scroll distance *is* playback time. A mouse notch is
 * ~100px, but one trackpad flick delivers momentum deltas an order of
 * magnitude past that — enough to cross a whole act between two frames. The
 * engine's own smoothing gives up at |Δ| > 3vh and snaps to the raw position
 * (see `index.ts`), so a hard flick doesn't scrub the act fast, it skips it.
 *
 * So take the wheel and meter it. Every gesture still travels in the
 * direction and roughly the distance the visitor asked for; it just cannot
 * arrive all at once. Two limits do the work:
 *
 *   SPEED   — how fast the page may move, in viewport heights per second.
 *   BACKLOG — how far ahead of the current position a gesture may queue.
 *
 * BACKLOG is the one that stops "I flicked once and it glided for six
 * seconds": without it the governor faithfully replays every momentum event
 * long after the fingers have left the pad, which reads as lag rather than
 * as control.
 *
 * Deliberately wheel-only. Keyboard (space, PageDown, arrows), scrollbar
 * drags and `scrollIntoView` stay entirely native — those are the
 * accessibility paths, and none of them can produce the runaway this exists
 * to catch. When one of them moves the page, the governor notices the
 * position moved without its say-so and hands control straight back.
 */

/** Ceiling on scroll speed, in viewport heights per second. */
const MAX_SPEED_VH = 2.4;
/** Most one gesture may queue ahead of where the page currently sits, in vh. */
const MAX_BACKLOG_VH = 2;
/** Larger than a sub-pixel rounding drift, smaller than any real scroll. */
const EPSILON = 2;

export interface ScrollGovernor {
  attach(): void;
  detach(): void;
  /** Advance the metered scroll. Call once per frame, before reading scrollY. */
  step(): void;
  /** Hand control back — something else is moving the page on purpose. */
  release(): void;
  /**
   * Rebase an in-flight gesture after the page was deliberately repositioned
   * by a known amount, as the act fold does. Releasing there instead would
   * drop the rest of the gesture on the floor: the fold is invisible — it
   * cuts spent runway and compensates with the scroll position — so the
   * visitor would see their flick produce no movement at all.
   */
  shift(dy: number): void;
}

/**
 * True when the wheel is over something that scrolls on its own (the lab
 * panels, the graph's side rail). Those keep native scrolling: metering a
 * 300px-tall overlay against the page's runway would be nonsense.
 */
function overOwnScroller(target: EventTarget | null): boolean {
  let el = target instanceof Element ? target : null;
  while (el && el !== document.body && el !== document.documentElement) {
    if (el.scrollHeight > el.clientHeight + EPSILON) {
      const overflow = getComputedStyle(el).overflowY;
      if (overflow === 'auto' || overflow === 'scroll') return true;
    }
    el = el.parentElement;
  }
  return false;
}

/** Wheel deltas arrive in px, lines or pages depending on the device. */
function deltaPx(e: WheelEvent): number {
  if (e.deltaMode === 1) return e.deltaY * 16; // lines
  if (e.deltaMode === 2) return e.deltaY * window.innerHeight; // pages
  return e.deltaY;
}

export function createScrollGovernor(): ScrollGovernor {
  /** Where the metered scroll is heading. Meaningless while `holding` is false. */
  let target = 0;
  /** True while the governor — rather than the browser — owns the position. */
  let holding = false;
  /** What we last told the page to do, so foreign movement is recognisable. */
  let applied = 0;
  let last = 0;
  /** Sign of the travel currently queued, so a reversal is recognisable. */
  let dir = 0;

  const maxScroll = () =>
    Math.max(0, document.documentElement.scrollHeight - window.innerHeight);

  const release = () => {
    holding = false;
    dir = 0;
  };

  const onWheel = (e: WheelEvent) => {
    // The explore-mode canvas takes the wheel for zoom and preventDefaults in
    // the target phase; this listener is on the bubble, so it sees that first.
    if (e.defaultPrevented) return;
    // Pinch-zoom and browser zoom arrive as ctrl+wheel. Never ours.
    if (e.ctrlKey || e.metaKey) return;
    // A modal or the gallery has locked the page; there is nothing to meter.
    if (document.body.style.overflow === 'hidden') return;
    if (overOwnScroller(e.target)) return;

    const dy = deltaPx(e);
    if (!dy) return;
    e.preventDefault();

    const sy = window.scrollY;
    if (!holding) {
      target = sy;
      // Re-baseline the foreign-movement check as well. Whatever moved the
      // page while we were released — a jump, a keypress, the act fold — left
      // `applied` pointing at a position that is now history, and step() would
      // read that gap as somebody else scrolling and hand control back on the
      // very next frame. Every wheel would acquire, every frame would release,
      // and the page would sit still.
      applied = sy;
      holding = true;
    }
    // A reversal takes effect now, not once the rest of the previous gesture
    // has played out. `target` may sit a whole backlog ahead of the page, so
    // adding an upward delta to it would spend most of the new gesture just
    // walking that queue back — the page carrying on downwards for the better
    // part of a second after the visitor asked it to stop. Whatever is still
    // queued in the old direction is abandoned instead: they have already
    // asked for something else.
    const sign = Math.sign(dy);
    if (sign !== dir) {
      target = sy;
      dir = sign;
    }
    const backlog = MAX_BACKLOG_VH * window.innerHeight;
    target = Math.min(sy + backlog, Math.max(sy - backlog, target + dy));
    target = Math.min(maxScroll(), Math.max(0, target));
  };

  const step = () => {
    const now = performance.now();
    // First frame has no interval; a tab that was backgrounded reports a huge
    // one. Cap it, or the catch-up step is exactly the lurch being prevented.
    const dt = last ? Math.min(0.05, (now - last) / 1000) : 0;
    last = now;
    if (!holding || !dt) return;

    const sy = window.scrollY;
    // Anything that moved the page without going through us — a keypress, a
    // scrollbar drag, an anchor jump — wins outright.
    if (Math.abs(sy - applied) > EPSILON) {
      release();
      return;
    }
    const remaining = target - sy;
    if (Math.abs(remaining) < 0.5) {
      release();
      return;
    }
    const limit = MAX_SPEED_VH * window.innerHeight * dt;
    const next = sy + Math.min(limit, Math.max(-limit, remaining));
    window.scrollTo(0, next);
    // Read back rather than trusting `next`: the browser clamps at the
    // document ends and rounds to device pixels, and a mismatch here would
    // read as foreign movement on the very next frame.
    applied = window.scrollY;
  };

  return {
    attach() {
      window.addEventListener('wheel', onWheel, { passive: false });
    },
    detach() {
      window.removeEventListener('wheel', onWheel);
      release();
    },
    step,
    release,
    shift(dy: number) {
      if (!holding) return;
      target = Math.min(maxScroll(), Math.max(0, target + dy));
      // The caller has already moved the page; take the post-move position as
      // the new baseline rather than assuming the shift landed exactly.
      applied = window.scrollY;
    },
  };
}
