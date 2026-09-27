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
 * Where in the collapse the panel hands over to the real card.
 *
 * The flight's easing puts nearly all the movement up front: measured, the
 * panel is already at card size about three quarters of the way through, and
 * the rest is settling. That is the moment to swap.
 *
 * Before this, the panel dissolved its contents to its own white ground and
 * then sat there, card-sized and blank, until the overlay unmounted — a solid
 * white card flashing where the real one was about to appear. It never turned
 * into the card; it turned into a white rectangle that was later replaced by
 * the card.
 *
 * So the contents are not cleared at all now. The demo stays up the whole way
 * down, and at the hand-off the card underneath is un-hidden and the panel
 * fades off it over the remaining quarter. What you see is the demo becoming
 * the card, with nothing blank in between.
 */
const HANDOFF = 0.74;
/** Safety net in case `onfinish` never fires (tab backgrounded mid-close). */
const CLOSE_FALLBACK_MS = CLOSE_MS + 240;
/** How long to wait before finishing when there is no card to fly back to. */
const NO_FLIP_MS = 200;
/** Used only if the card's own radius cannot be read; mirrors `CARD` in Gallery.tsx. */
const FALLBACK_CARD_RADIUS = 20;

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
 * The counter-scale that keeps the panel's CONTENTS in proportion.
 *
 * The panel and the card are different shapes: 1440x900 is 1.60 wide, a
 * 372x314 card is 1.18. Squeezing one into the other is a non-uniform scale —
 * 0.258 across against 0.349 down at that size — so everything inside came out
 * 35% narrower than it was tall. Type condensed, the avatar an oval, the whole
 * demo subtly wrong in a way that reads as cheap rather than as small.
 *
 * So the BOX still takes the non-uniform scale, because it has to land exactly
 * on the card, and the contents take the inverse of the difference. Both
 * multiply out to the same uniform factor — the larger of the two, so the
 * contents cover the box rather than leaving a gap — and what is left over
 * runs past the edge, where the panel's own `overflow: hidden` clips it.
 *
 * The result reads as a crop of the demo rather than a squashed copy of it,
 * which is what zooming into something actually looks like. Whichever axis is
 * already the larger gets a factor of exactly 1, so this is a no-op on a card
 * that happens to share the viewport's aspect ratio.
 */
function counterScale(sx: number, sy: number): string {
  const s = Math.max(sx, sy);
  return 'scale(' + (s / sx).toFixed(4) + ',' + (s / sy).toFixed(4) + ')';
}

/** Keyframes for the panel's children: cropped-and-proportional, then at rest. */
export function contentFrames(sx: number, sy: number): Keyframe[] {
  return [
    { transformOrigin: 'top left', transform: counterScale(sx, sy) },
    { transformOrigin: 'top left', transform: 'none' },
  ];
}

/**
 * The scale the panel is flown at, exposed so the contents can undo its
 * distortion. Null when there is nothing to fly from.
 */
export function flipScale(st: FlipState, panel: HTMLElement): { sx: number; sy: number } | null {
  const r = st.rect;
  if (!r) return null;
  const p = panel.getBoundingClientRect();
  if (!p.width || !p.height) return null;
  return { sx: Math.max(0.05, r.width / p.width), sy: Math.max(0.05, r.height / p.height) };
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

  /*
   * The corner radius has to be divided by the scale, not stated flat.
   *
   * A transform scales an element's border-radius along with everything else,
   * so the panel's declared 20px arrived at card size rendering as 5.2 x 7.0px
   * — near enough square against a card with genuinely round 20px corners, and
   * the reason the expansion did not look like it came out of the card. The
   * panel has to declare 20/scale so that what lands on screen is 20.
   *
   * Elliptical, using the `horizontal / vertical` form, because the scale is
   * not uniform: a card is 372x314 against a 1440x900 viewport, so x and y
   * shrink by quite different factors (0.258 against 0.349 there). One flat
   * value compensated for both would come out visibly oval on one axis.
   *
   * The radius is read off the card itself rather than restated here, so it
   * cannot drift from `CARD` in Gallery.tsx.
   */
  const cardRadius = st.el
    ? parseFloat(getComputedStyle(st.el).borderTopLeftRadius) || FALLBACK_CARD_RADIUS
    : FALLBACK_CARD_RADIUS;

  return [
    {
      transformOrigin: 'top left',
      transform:
        'translate(' + (r.left - p.left) + 'px,' + (r.top - p.top) + 'px) scale(' + sx + ',' + sy + ')',
      borderRadius: (cardRadius / sx).toFixed(1) + 'px / ' + (cardRadius / sy).toFixed(1) + 'px',
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

  // Read the scale BEFORE starting the flight. `flipScale` measures the panel,
  // and once the transform is running that measurement is of the scaled box,
  // not the full-size one — which silently yields a counter-scale of 1 and no
  // correction at all.
  const sc = flipScale(st, panel);

  panel.animate(f, { duration: OPEN_MS, easing: OPEN_EASE, fill: 'both' });

  if (sc) {
    const cf = contentFrames(sc.sx, sc.sy);
    for (const child of Array.from(panel.children)) {
      if (!(child instanceof HTMLElement) || !child.animate) continue;
      // Deliberately NOT cancelling the child's existing animations. They are
      // the `panelFade` CSS rules that stagger the demo in over the expansion,
      // and clearing them made the contents appear fully painted on frame one —
      // losing the very thing that keeps the open from reading as a white
      // flash. There is nothing to stack with anyway: the overlay unmounts on
      // close, so these children are new on every open.
      child.animate(cf, { duration: OPEN_MS, easing: OPEN_EASE, fill: 'both' });
    }
  }
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
  // Declared with an explicit `undefined` rather than left bare: `finish` closes
  // over it and the no-card path below calls `finish` before the assignment is
  // reached, so a `const` at the assignment site would be a TDZ error there.
  let reveal: ReturnType<typeof setTimeout> | undefined = undefined;
  const finish = () => {
    if (done) return;
    done = true;
    if (reveal !== undefined) clearTimeout(reveal);
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
  // Measured here, alongside the frames, for the reason spelled out in
  // `flipOpen`: once the flight is running the panel no longer measures its
  // full size.
  const sc = flipScale(st, panel);
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

  // Un-hide the card just as the panel arrives on it, then fade the panel off
  // it. The card is underneath at the same rect by then, so what the fade
  // reveals is the card itself rather than the gallery — which is why this is
  // safe to do to the whole panel, background and all, where fading it mid
  // flight would have shown the rail sliding under a transparent hole.
  const handoffAt = CLOSE_MS * HANDOFF;
  reveal = setTimeout(() => { if (st.el) st.el.style.visibility = ''; }, handoffAt);

  panel.animate(
    [{ opacity: 1, offset: 0 }, { opacity: 1, offset: HANDOFF }, { opacity: 0, offset: 1 }],
    { duration: CLOSE_MS, easing: 'linear', fill: 'both' },
  );

  // ...and the contents give their proportions back on the way down, so the
  // demo crops rather than squashes as the box changes shape.
  if (sc) {
    const cf = contentFrames(sc.sx, sc.sy);
    for (const child of Array.from(panel.children)) {
      if (!(child instanceof HTMLElement) || !child.animate) continue;
      child.animate([cf[1], cf[0]], { duration: CLOSE_MS, easing: CLOSE_EASE, fill: 'both' });
    }
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
