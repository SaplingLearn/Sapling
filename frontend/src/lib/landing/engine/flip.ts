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
const CLOSE_MS = 460;
const CLOSE_EASE = 'cubic-bezier(0.4,0,0.2,1)';
/** Safety net in case `onfinish` never fires (tab backgrounded mid-close). */
const CLOSE_FALLBACK_MS = 700;
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
  const a = panel.animate([f[1], f[0]], {
    duration: CLOSE_MS,
    easing: CLOSE_EASE,
    fill: 'both',
  });
  a.onfinish = finish;
  setTimeout(finish, CLOSE_FALLBACK_MS);
}
