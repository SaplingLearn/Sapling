/**
 * Dual-row gallery marquee — auto-drift, hover pause, drag with momentum.
 *
 * Ported from `Sapling Landing v4.dc.html`. Each track holds its card set
 * twice; `off` wraps modulo the width of one set, so the loop is seamless
 * without ever cloning or reflowing.
 *
 * A press is a tap or a drag depending on distance travelled: under 6px opens
 * the card, over 4px sets the shared `dragged` flag so the click that follows
 * is swallowed.
 */

export interface MarqueeTrackState {
  dir: number;
  /** Current scroll offset in px, always wrapped into [0, setW). */
  off: number;
  /** Momentum, px per ms. */
  v: number;
  speed: number;
  paused: boolean;
  drag: { x: number; y: number; off: number; lastX: number; lastT: number; moved: number } | null;
  /** Width of one card set; 0 until measured. */
  setW: number;
  measuredW: number;
  downCard: number;
  downEl: HTMLElement | null;
}

export interface MarqueeOptions {
  /** Fired on tap (not drag). */
  onOpen(index: number, from: HTMLElement | null): void;
  /** Mirrors the source's `_mqDragged`, used to suppress the trailing click. */
  setDragged(v: boolean): void;
}

export interface MarqueeController {
  bind(track: HTMLElement, dir: number): void;
  update(now: number): void;
  /**
   * Reset the drift clock. Called on every frame the gallery is off-screen so
   * that re-entering doesn't apply the whole elapsed gap as one jump.
   */
  resetClock(now: number): void;
  destroy(): void;
}

const STATE = new WeakMap<HTMLElement, MarqueeTrackState>();

export function createMarquee(opts: MarqueeOptions): MarqueeController {
  const tracks: HTMLElement[] = [];
  const cleanups: (() => void)[] = [];
  let last = 0;

  function bind(track: HTMLElement, dir: number): void {
    if (STATE.has(track)) return;
    const m: MarqueeTrackState = {
      dir, off: 0, v: 0, speed: 26, paused: false, drag: null,
      setW: 0, measuredW: -1, downCard: -1, downEl: null,
    };
    STATE.set(track, m);
    tracks.push(track);

    const wrap = track.parentElement;
    const onEnter = () => { m.paused = true; };
    const onLeave = () => { m.paused = false; };
    wrap?.addEventListener('pointerenter', onEnter);
    wrap?.addEventListener('pointerleave', onLeave);

    const onDown = (e: PointerEvent) => {
      const target = e.target as Element | null;
      const card = target?.closest?.('[data-tk]') as HTMLElement | null;
      m.downCard = card ? parseInt(card.dataset.tk as string, 10) : -1;
      m.downEl = card || null;
      m.drag = {
        x: e.clientX, y: e.clientY, off: m.off,
        lastX: e.clientX, lastT: performance.now(), moved: 0,
      };
      m.v = 0;
      opts.setDragged(false);
      try { track.setPointerCapture(e.pointerId); } catch { /* not captureable */ }
      track.style.cursor = 'grabbing';
    };

    const onMove = (e: PointerEvent) => {
      if (!m.drag) return;
      const dx = e.clientX - m.drag.x;
      m.drag.moved = Math.max(m.drag.moved, Math.hypot(dx, e.clientY - m.drag.y));
      if (m.drag.moved > 4) opts.setDragged(true);
      m.off = m.drag.off - dx;
      const t = performance.now();
      const dt = Math.max(1, t - m.drag.lastT);
      m.v = -(e.clientX - m.drag.lastX) / dt;
      m.drag.lastX = e.clientX;
      m.drag.lastT = t;
    };

    const end = (cancelled: boolean) => {
      if (!m.drag) return;
      const tapped = m.drag.moved < 6;
      m.drag = null;
      track.style.cursor = 'grab';
      if (!cancelled && tapped && m.downCard >= 0) opts.onOpen(m.downCard, m.downEl);
      m.downCard = -1;
      m.downEl = null;
      // let the click that follows a drag pass before clearing the flag
      setTimeout(() => opts.setDragged(false), 60);
    };
    const onUp = () => end(false);
    const onCancel = () => end(true);

    track.addEventListener('pointerdown', onDown);
    track.addEventListener('pointermove', onMove);
    track.addEventListener('pointerup', onUp);
    track.addEventListener('pointercancel', onCancel);
    // Also on window, the same way `sim.ts` binds its drag release.
    // `setPointerCapture` above is in a try/catch: when capture fails, a drag
    // that ends outside `track` never fires the track-scoped pointerup, so
    // `m.drag` stayed non-null — drift and momentum froze and the cursor was
    // stuck at `grabbing` until the next pointerdown. `end()` no-ops when
    // there is no drag, so the duplicate binding is harmless.
    window.addEventListener('pointerup', onUp);
    window.addEventListener('pointercancel', onCancel);

    cleanups.push(() => {
      wrap?.removeEventListener('pointerenter', onEnter);
      wrap?.removeEventListener('pointerleave', onLeave);
      track.removeEventListener('pointerdown', onDown);
      track.removeEventListener('pointermove', onMove);
      track.removeEventListener('pointerup', onUp);
      track.removeEventListener('pointercancel', onCancel);
      window.removeEventListener('pointerup', onUp);
      window.removeEventListener('pointercancel', onCancel);
      STATE.delete(track);
    });
  }

  function update(now: number): void {
    const dt = Math.min(48, now - (last || now));
    last = now;
    tracks.forEach((track) => {
      const m = STATE.get(track);
      if (!m) return;
      const wrap = track.parentElement;
      if (!wrap) return;
      // measure one card set only when the container width changed
      if (!m.setW || m.measuredW !== wrap.clientWidth) {
        const kids = track.children;
        const half = kids.length / 2;
        const gap = parseFloat(getComputedStyle(track).columnGap) || 0;
        let w = 0;
        for (let i = 0; i < half; i++) w += (kids[i] as HTMLElement).offsetWidth + gap;
        // A zero sum means the cards are not laid out yet. Accepting it stored
        // the `w || 1` fallback together with the current `measuredW`, so the
        // track wrapped every frame at 1px and never re-measured until the
        // viewport resized. Leaving `setW` at 0 retries on the next frame.
        if (w > 0) {
          m.setW = w;
          m.measuredW = wrap.clientWidth;
        }
      }
      // Still unmeasured: nothing sensible to wrap against this frame.
      if (!m.setW) return;
      if (!m.drag) {
        if (Math.abs(m.v) > 0.004) {
          m.off += m.v * dt;
          // frame-rate independent decay
          m.v *= Math.pow(0.92, dt / 16.7);
        } else {
          m.v = 0;
        }
        if (!m.paused) m.off -= (m.dir * m.speed * dt) / 1000;
      }
      m.off = ((m.off % m.setW) + m.setW) % m.setW;
      track.style.transform = 'translate3d(' + (-m.off).toFixed(2) + 'px,0,0)';
    });
  }

  function resetClock(now: number): void {
    last = now;
  }

  function destroy(): void {
    cleanups.forEach((fn) => fn());
    cleanups.length = 0;
    tracks.length = 0;
  }

  return { bind, update, resetClock, destroy };
}
