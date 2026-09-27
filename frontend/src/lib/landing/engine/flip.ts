/**
 * FLIP transition for the feature lab — a gallery card expands into the
 * full-bleed overlay and collapses back into the card it came from.
 *
 * Ported from `Sapling Landing v4.dc.html`. Uses the Web Animations API
 * directly (as the source does): the panel renders at its final size, then
 * gets animated *from* the card's rect, so there is no layout thrash and the
 * browser can run the whole thing off the main thread.
 */

const OPEN_MS = 620;
const OPEN_EASE = 'cubic-bezier(0.22,1,0.36,1)';
/*
 * The close is the open played backwards: same distance, same curve, same
 * time, and therefore the same speed.
 *
 * Both halves of that matter. The curve used to be
 * `cubic-bezier(0.4,0,0.2,1)` against the open's
 * `cubic-bezier(0.22,1,0.36,1)`, so the panel left by a different route than
 * it arrived by. And the duration was briefly cut — on the theory that an
 * exit is only getting out of the way and should not dawdle — but the panel
 * covers the same ground either way, so a shorter close is literally a faster
 * one, and the pair stopped reading as one gesture reversed.
 *
 * What made the close feel slow was never its duration: a full re-render of
 * the landing tree sat between the click and the first frame, and it is gone
 * (see the `modalAnim` removal). At the same 620ms the whole close now
 * completes in about the time the shortened one used to take.
 */
const CLOSE_MS = OPEN_MS;
const CLOSE_EASE = OPEN_EASE;
/*
 * How long the panel's contents take to clear, as the box collapses.
 *
 * This is the open's content timing, reversed — and the reversal is the whole
 * point. On the way in, `panelFade` holds the demo at zero for the first
 * 160ms of a 620ms box and has it fully painted by 580ms: the panel is blank
 * only while it is still SMALL, and by the time it fills the screen there is
 * something in it. Nobody reads that as a white flash, because the white is
 * never big.
 *
 * Clearing the contents quickly did the opposite. At a quarter of the flight
 * the panel went blank while still near full-screen, and the remaining
 * three quarters were a full-bleed white rectangle shrinking — which is
 * exactly the flash this was meant to avoid, just pointed the other way.
 *
 * 0.74 of the flight is 1 − 0.26: the demo stays up while the box is large
 * and is gone by the time it is card-sized, so the white phase lands in the
 * last quarter of the close and mirrors the first quarter of the open.
 * `ease-in` keeps it near full opacity early and drops it late, so the fade
 * tracks the box getting small rather than running ahead of it.
 */
const CONTENT_CLEAR_MS = Math.round(CLOSE_MS * 0.74);
/** Safety net in case `onfinish` never fires (tab backgrounded mid-close). */
const CLOSE_FALLBACK_MS = CLOSE_MS + 240;
/** How long to wait before finishing when there is no card to fly back to. */
const NO_FLIP_MS = 200;

export interface FlipState {
  /** The originating card's rect, captured before the overlay mounts. */
  rect: DOMRect | null;
  el: HTMLElement | null;
  /** Guards against the open animation running twice for one mount. */
  ran: boolean;
}

export function createFlipState(): FlipState {
  return { rect: null, el: null, ran: false };
}

/**
 * Capture the source card. Pass `null` when opening without one.
 *
 * Re-arming RESTORES whatever the previous open hid. `flipOpen` takes the
 * card out of the rail with `visibility: hidden` so the panel can stand in
 * for it, and only `flipClose` puts it back — so overwriting `st.el` used to
 * drop the one reference that could ever un-hide that card, stranding it
 * invisible in the marquee for the rest of the session. Every re-arm is a
 * point where that could happen, so the restore belongs here rather than at
 * each call site.
 */
export function armFlip(st: FlipState, from: HTMLElement | null): void {
  if (st.el && st.el !== from) st.el.style.visibility = '';
  st.rect = from ? from.getBoundingClientRect() : null;
  st.el = from;
  st.ran = false;
}

/**
 * Re-measure the card already armed, without changing which card it is.
 *
 * The rail drifts continuously, so a rect captured when the visitor clicked
 * is stale by the time they switch demos. Re-reading it keeps the expansion
 * anchored to where that card actually is now. A hidden element still has a
 * box, so `visibility: hidden` does not get in the way.
 */
export function remeasureFlip(st: FlipState): void {
  if (st.el) st.rect = st.el.getBoundingClientRect();
}

/**
 * The two keyframes: the panel scaled down onto the card, and the panel at
 * rest. Returns null when there is nothing to fly from.
 */
export function flipFrames(st: FlipState, panel: HTMLElement): Keyframe[] | null {
  const r = st.rect;
  if (!r || !panel.animate) return null;
  const p = panel.getBoundingClientRect();
  if (!p.width || !p.height) return null;
  const sx = Math.max(0.05, r.width / p.width);
  const sy = Math.max(0.05, r.height / p.height);
  return [
    {
      transformOrigin: 'top left',
      transform:
        'translate(' + (r.left - p.left) + 'px,' + (r.top - p.top) + 'px) scale(' + sx + ',' + sy + ')',
      borderRadius: '20px',
    },
    { transformOrigin: 'top left', transform: 'none', borderRadius: '0px' },
  ];
}

/**
 * Play the card → panel expansion. Hides the card while the panel stands in.
 *
 * Any animation already on the panel is cancelled first. Replaying the
 * expansion for a demo switch would otherwise stack a second animation on
 * top of one still filling `both`, and the two compose into a transform
 * neither keyframe asked for.
 */
export function flipOpen(st: FlipState, panel: HTMLElement): void {
  const f = flipFrames(st, panel);
  if (!f) return;
  panel.getAnimations().forEach((a) => a.cancel());
  if (st.el) st.el.style.visibility = 'hidden';
  panel.animate(f, { duration: OPEN_MS, easing: OPEN_EASE, fill: 'both' });
}

/**
 * Play the panel → card collapse, then run `onFinish` exactly once.
 * `onFinish` should restore body scroll and unmount the overlay.
 */
export function flipClose(
  st: FlipState,
  panel: HTMLElement | null,
  onFinish: () => void,
): void {
  st.ran = false;
  // Re-read the card before flying to it. The rect was captured when the
  // visitor clicked, and anything that moved the rail since — a resize, or a
  // frame of drift before the marquee was held — would land the panel beside
  // its card instead of on it.
  remeasureFlip(st);
  let done = false;
  const finish = () => {
    if (done) return;
    done = true;
    if (st.el) {
      st.el.style.visibility = '';
      st.el = null;
    }
    onFinish();
  };

  const f = panel ? flipFrames(st, panel) : null;
  if (!f || !panel) {
    setTimeout(finish, NO_FLIP_MS);
    return;
  }
  // The flight is created FIRST, before either fade below.
  //
  // Ordering is not cosmetic here. Animating opacity across the panel's whole
  // subtree — a full demo, canvases and all — costs enough style work that
  // doing it first pushed the collapse's start time ~180ms past the click: a
  // 409ms animation was reporting `finish` at 591ms, and the visitor was
  // watching a still panel for the difference. Starting the transform first
  // lets the compositor own it while the rest is set up.
  const a = panel.animate([f[1], f[0]], {
    duration: CLOSE_MS,
    easing: CLOSE_EASE,
    fill: 'both',
  });

  // Dissolve the contents to the panel's own white ground as it goes. Every
  // direct child is faded rather than the panel itself: fading the panel would
  // take its background with it and the card would be flown back to by a
  // transparent hole, with the gallery sliding underneath.
  for (const child of Array.from(panel.children)) {
    if (!(child instanceof HTMLElement) || !child.animate) continue;
    child.animate([{ opacity: 1 }, { opacity: 0 }], {
      duration: CONTENT_CLEAR_MS,
      easing: 'ease-in',
      fill: 'both',
    });
  }

  // The scrim goes with it. The opening fades this in (`panelFade`) while the
  // white box grows; the close used to leave it at full strength until the
  // overlay unmounted, so the backdrop vanished in one frame the instant the
  // box landed. Taking it down over the same flight is the other half of
  // playing the open backwards.
  const scrim = panel.previousElementSibling;
  if (scrim instanceof HTMLElement && scrim.animate) {
    scrim.animate([{ opacity: 1 }, { opacity: 0 }], {
      duration: CLOSE_MS,
      easing: CLOSE_EASE,
      fill: 'both',
    });
  }

  a.onfinish = finish;
  setTimeout(finish, CLOSE_FALLBACK_MS);
}
