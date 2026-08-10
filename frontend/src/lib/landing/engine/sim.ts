/**
 * Drag-field force simulation — the little graph clusters the visitor can
 * pull apart with the pointer.
 *
 * Ported from `Sapling Landing v4.dc.html`. Deliberately hand-rolled rather
 * than delegated to `d3-force` (which is already a dependency): the forces
 * are expressible in d3, but this integrator uses a *linear* alpha ramp
 * toward a target instead of d3's exponential decay, resolves collide in a
 * single pass rather than d3's iterated one, and adds an idle breathing
 * drift plus an anchor spring back to each node's home. Same forces,
 * different settling — swapping in d3 changes how it feels.
 *
 * One force is answerable to the visitor rather than the layout: a node
 * dropped away from where it started is *placed*, and a placed node is out of
 * the simulation for as long as it stays there. See `SimNode.placed`.
 *
 * Writes `cx`/`cy` straight onto the SVG elements. No React, no canvas.
 */

const OVERLAY_CLASS = 'drag-overlay';
const SHELL_CLASS = 'drag-shell';

/**
 * How long after the last scroll event the sim stays frozen.
 *
 * While the page is scrolling the clusters must read as part of the page:
 * `syncClusters()` keeps translating them with their section, and nothing
 * else may move. Integrating during a scroll is what made a node visibly
 * swim against the copy it belongs to — the idle breathing drift and the
 * anchor spring are both a few px/frame, which is invisible on a still page
 * and obvious as independent motion once everything around it is moving.
 *
 * A held node is exempt: it has to keep tracking the pointer.
 */
const SCROLL_QUIET_MS = 140;

/**
 * Autoscroll band at the top and bottom of the viewport, active only while a
 * node is held. Dragging into it scrolls the page, which is what lets a node
 * be carried out of its own section and across the whole document — without
 * it, "drag down" ends at the bottom of the screen.
 */
const EDGE_BAND_PX = 110;
/** Peak autoscroll speed in px/frame, reached at the very edge of the band. */
const EDGE_SPEED_PX = 22;

/*
 * There is deliberately no rejoin radius.
 *
 * A drop used to count as "put back" if it landed within 70px of the node's
 * home, which re-floated it: the spring retargeted to the original spot and
 * the ambient breathing restarted. That made every short drag spring back —
 * measured at 14px of travel still climbing 4s after a 40px drag, against 0px
 * for a 90px one — and short drags are most of them. A drop now always places
 * the node, at any distance. The cost is that there is no way to put a node
 * back in its cluster short of a reload; that is the intended trade.
 */

interface SimNode {
  x: number; y: number;
  vx: number; vy: number;
  /** Non-null while pinned to the pointer. */
  fx: number | null; fy: number | null;
  r: number;
  root: boolean;
  cluster: number;
  collide: number;
  charge: number;
  ring: SVGCircleElement;
  glow: SVGCircleElement;
  label: SVGTextElement;
  /** Label's y offset from its ring. */
  ly: number;
  /** Home position, which the anchor spring pulls back toward. */
  hx: number; hy: number;
  /**
   * True once the visitor has dropped this node somewhere of their own
   * choosing. A placed node holds that spot: it takes no part in its
   * cluster's link, charge or collide forces, and stops breathing. Without
   * that it is pulled straight back — the link spring alone wants its
   * neighbours 34-86px away, which no amount of re-homing survives.
   */
  placed: boolean;
}

interface SimLink {
  a: number;
  b: number;
  el: SVGLineElement;
  /** Normalised stroke weight, 0..1 — heavier links sit closer. */
  s: number;
}

/** A cluster's fixed offset inside its (often sticky) field. */
interface ClusterAnchor {
  el: HTMLElement;
  field: HTMLElement;
  left: number;
  top: number;
  /**
   * The copy this cluster travels with, when that copy pins independently of
   * the field. Null for the ordinary case, where the field's own rect already
   * carries every movement the cluster needs.
   */
  track: HTMLElement | null;
  /** `track.top - field.top` at build time, i.e. before either has pinned. */
  trackTop: number;
}

/**
 * One cluster's svg mapped into viewport space, so a held node can be clamped
 * to what the visitor can actually see.
 */
interface ClusterBox {
  left: number; top: number;
  /** px per viewBox unit. */
  sx: number; sy: number;
  vbx: number; vby: number;
}

interface SimGroup {
  field: HTMLElement;
  clusters: HTMLElement[];
  nodes: SimNode[];
  links: SimLink[];
  alpha: number;
  target: number;
  drag: {
    n: SimNode; id: number; svg: SVGSVGElement; cx: number; cy: number;
    /**
     * Where the puck and its concepts sat the moment it was grabbed, so the
     * drop can rebuild that formation around wherever it lands. Empty unless
     * a course puck is the node being dragged.
     */
    carry: { q: SimNode; dx: number; dy: number }[];
  } | null;
}

export interface SimController {
  /** Lazily builds the sim; returns false until the fields are laid out. */
  ensureInit(root: HTMLElement): boolean;
  step(vh: number, t: number): void;
  destroy(): void;
}

export function createSim(): SimController {
  let groups: SimGroup[] | null = null;
  let overlay: HTMLDivElement | null = null;
  const anchors: ClusterAnchor[] = [];
  const cleanups: (() => void)[] = [];
  /** Timestamp of the last scroll event, on the same clock as the rAF `t`. */
  let lastScrollAt = -Infinity;

  /**
   * Re-seats every cluster against its field's live rect, once per frame.
   *
   * Cheap by construction: a handful of `getBoundingClientRect()` reads and
   * one transform write each, all on elements parked in a fixed overlay, so
   * nothing here can invalidate the page's layout.
   *
   * Strictly `field.rect + anchor`, with nothing added: the cluster is welded
   * to the section it belongs to and translates with it 1:1. An earlier
   * version drifted a cluster up to 150px against the scroll inside a pinned
   * act, on the theory that it kept the field from looking stuck to the copy.
   * It reads as the cluster sliding under the page instead — the one thing a
   * decorative overlay must never do — so the drift is gone.
   *
   * The one sanctioned addition is `track`, and it exists to preserve that
   * same 1:1 rule rather than break it. A field's rect only speaks for its
   * copy while the two move together; where the copy pins on its own — the
   * FAQ's sticky question column against a static section — the field keeps
   * scrolling and the clusters slide out from under the words. Measured at
   * 374px through `faq`, which is exactly that column's sticky travel
   * (`grid 733px - column 358px`). Re-adding the tracked element's own travel
   * puts the cluster back on the copy for every frame of the pin and the
   * release. A field with no tracked copy is untouched by this.
   */
  function syncClusters(): void {
    for (const a of anchors) {
      if (!a.field.isConnected) continue;
      const r = a.field.getBoundingClientRect();
      // How far the copy has pinned away from its field since build time.
      let dy = 0;
      if (a.track?.isConnected) {
        dy = a.track.getBoundingClientRect().top - r.top - a.trackTop;
      }
      a.el.style.transform =
        'translate3d(' + (r.left + a.left).toFixed(1) + 'px,' +
        (r.top + a.top + dy).toFixed(1) + 'px,0)';
    }
  }

  /** The held cluster's svg in viewport space, or null if it isn't laid out. */
  function boxFor(svg: SVGSVGElement): ClusterBox | null {
    const r = svg.getBoundingClientRect();
    const vb = svg.viewBox?.baseVal;
    if (!r.width || !r.height || !vb || !vb.width || !vb.height) return null;
    return {
      left: r.left, top: r.top,
      sx: r.width / vb.width, sy: r.height / vb.height,
      vbx: vb.x, vby: vb.y,
    };
  }

  function ensureInit(root: HTMLElement): boolean {
    if (groups) return true;
    const fields = Array.from(root.querySelectorAll<HTMLElement>('.drag-field'));
    if (!fields.length) return false;
    // hidden below 1024px by the media query — don't build it at all
    if (getComputedStyle(fields[0]).display === 'none') return false;

    if (!overlay) {
      // Two elements, and the outer one is load-bearing.
      //
      // The shell is `position:fixed`, so the absolute overlay inside it is
      // in viewport coordinates — which is the space `syncClusters()` writes
      // its per-frame transforms in. It also clips (`overflow:hidden`), so a
      // thrown node can never extend the page, and carries
      // `touch-action:none` so dragging a node doesn't scroll instead.
      const shell = document.createElement('div');
      shell.className = SHELL_CLASS;
      shell.setAttribute('aria-hidden', 'true');
      shell.style.cssText =
        'position:fixed; inset:0; overflow:hidden; z-index:45; pointer-events:none; touch-action:none;';

      overlay = document.createElement('div');
      overlay.className = OVERLAY_CLASS;
      overlay.setAttribute('aria-hidden', 'true');
      overlay.style.cssText =
        'position:absolute; top:0; left:0; width:100%; height:0; pointer-events:none; overflow:visible; will-change:transform;';

      shell.appendChild(overlay);
      root.appendChild(shell);
      cleanups.push(() => shell.remove());
    }

    const built: SimGroup[] = [];
    fields.forEach((field) => {
      const clusters = Array.from(field.querySelectorAll<HTMLElement>('[data-dragnode]'));
      if (!clusters.length) return;

      // Re-home each cluster in the overlay so its parts can travel outside
      // the section's bounds, remembering its offset WITHIN ITS FIELD.
      //
      // Field-relative, not page- or overlay-relative. Most of these fields
      // are `position:sticky`, so their own rect moves as the page scrolls;
      // `syncClusters()` re-applies `anchor + field.rect` every frame, which
      // is what makes a cluster track the section it belongs to. Baking a
      // one-shot absolute left/top here instead freezes every cluster at
      // whatever the layout happened to be on the first frame.
      // Opt-in, and resolved once: the copy this field's clusters belong to,
      // when it pins independently of the field. See `syncClusters()`.
      const sel = field.dataset.dragTrack;
      const track = sel
        ? (field.closest('section') ?? document).querySelector<HTMLElement>(sel)
        : null;

      clusters.forEach((cl) => {
        const fb = field.getBoundingClientRect();
        const b = cl.getBoundingClientRect();
        anchors.push({
          el: cl, field,
          left: b.left - fb.left,
          top: b.top - fb.top,
          track,
          trackTop: track ? track.getBoundingClientRect().top - fb.top : 0,
        });
        cl.style.animation = 'none';
        cl.style.position = 'absolute';
        cl.style.left = '0px';
        cl.style.top = '0px';
        cl.style.right = 'auto';
        cl.style.bottom = 'auto';
        cl.style.willChange = 'transform';
        overlay!.appendChild(cl);
      });

      const nodes: SimNode[] = [];
      const links: SimLink[] = [];
      clusters.forEach((cl, ci) => {
        const svg = cl.querySelector('svg');
        if (!svg) return;
        const rings = Array.from(svg.querySelectorAll<SVGCircleElement>('[data-sim]'));
        const lines = Array.from(svg.querySelectorAll('line'));
        const base = nodes.length;

        rings.forEach((ring, ri) => {
          const r = parseFloat(ring.getAttribute('r') || '0');
          const glow = ring.previousElementSibling as SVGCircleElement;
          const label = ring.nextElementSibling as SVGTextElement;
          nodes.push({
            x: parseFloat(ring.getAttribute('cx') || '0'),
            y: parseFloat(ring.getAttribute('cy') || '0'),
            vx: 0, vy: 0, fx: null, fy: null, r,
            root: ri === 0, cluster: ci,
            // the root sits heavier and pushes harder than its satellites
            collide: ri === 0 ? 30 : 15 + r * 0.5,
            charge: ri === 0 ? -400 : -120,
            ring, glow, label,
            ly: parseFloat(label.getAttribute('y') || '0') - parseFloat(ring.getAttribute('cy') || '0'),
            hx: 0, hy: 0,
            placed: false,
          });
        });

        lines.forEach((ln) => {
          // match each line end to the nearest ring in this cluster
          const near = (x: number, y: number) => {
            let best = -1;
            let bd = 1e9;
            for (let k = base; k < nodes.length; k++) {
              const d = Math.hypot(nodes[k].x - x, nodes[k].y - y);
              if (d < bd) { bd = d; best = k; }
            }
            return best;
          };
          const a = near(parseFloat(ln.getAttribute('x1') || '0'), parseFloat(ln.getAttribute('y1') || '0'));
          const b = near(parseFloat(ln.getAttribute('x2') || '0'), parseFloat(ln.getAttribute('y2') || '0'));
          links.push({ a, b, el: ln, s: (parseFloat(ln.getAttribute('stroke-width') || '0.5') - 0.5) / 1.2 });
        });

        // the cluster no longer floats as a unit; the sim moves its parts
        cl.style.animation = 'none';
        const puck = cl.querySelector<HTMLElement>('[data-dragpuck]');
        if (puck) puck.style.transform = 'none';
        svg.style.overflow = 'visible';
      });

      nodes.forEach((n) => { n.hx = n.x; n.hy = n.y; });
      built.push({ field, clusters, nodes, links, alpha: 1, target: 0, drag: null });
    });

    if (!built.length) return false;
    groups = built;
    bindDrag();

    // Passive, and the only thing it does is stamp a time — the freeze itself
    // is decided in `step()` so it stays on the frame clock.
    const onScroll = () => { lastScrollAt = performance.now(); };
    window.addEventListener('scroll', onScroll, { passive: true });
    cleanups.push(() => window.removeEventListener('scroll', onScroll));
    return true;
  }

  function bindDrag(): void {
    groups!.forEach((f) => {
      f.clusters.forEach((cl) => {
        const svg = cl.querySelector('svg');
        if (!svg) return;
        // client coords → viewBox coords
        const local = (e: PointerEvent) => {
          const r = svg.getBoundingClientRect();
          const vb = svg.viewBox.baseVal;
          const sx = vb && vb.width ? vb.width / r.width : 1;
          const sy = vb && vb.height ? vb.height / r.height : 1;
          return {
            x: (vb ? vb.x : 0) + (e.clientX - r.left) * sx,
            y: (vb ? vb.y : 0) + (e.clientY - r.top) * sy,
          };
        };

        const onDown = (e: PointerEvent) => {
          const target = e.target as Element | null;
          const ring = target?.closest?.('[data-sim]') as SVGCircleElement | null;
          if (!ring) return;
          e.preventDefault();
          const n = f.nodes.find((x) => x.ring === ring);
          if (!n) return;
          const p = local(e);
          // Snapshot the cluster's shape now, not at the drop. The link force
          // tows the concepts along during the drag, but it is a spring and a
          // fast flick outruns it — leaving them strung out behind the puck,
          // which is the shape a drop would otherwise freeze. Offsets taken
          // here are the settled formation the visitor actually grabbed.
          const carry = n.root
            ? f.nodes
              .filter((q) => q !== n && q.cluster === n.cluster)
              .map((q) => ({ q, dx: q.x - n.x, dy: q.y - n.y }))
            : [];
          f.drag = { n, id: e.pointerId, svg, cx: e.clientX, cy: e.clientY, carry };
          n.fx = p.x;
          n.fy = p.y;
          f.target = 0.3;
          f.alpha = Math.max(f.alpha, 0.6);
          svg.style.cursor = 'grabbing';
          ring.setAttribute('stroke-opacity', '1');
          try { svg.setPointerCapture(e.pointerId); } catch { /* not captureable */ }
        };

        const onMove = (e: PointerEvent) => {
          if (!f.drag || f.drag.id !== e.pointerId || f.drag.svg !== svg) return;
          f.drag.cx = e.clientX;
          f.drag.cy = e.clientY;
          const p = local(e);
          f.drag.n.fx = p.x;
          f.drag.n.fy = p.y;
        };

        const up = (e: PointerEvent) => {
          if (!f.drag) return;
          // The held cluster's svg, NOT this listener's. `up` is bound to
          // window for every cluster, so the one that runs first is not
          // necessarily the one holding the pointer, and converting the drop
          // through the wrong svg puts the node somewhere else entirely.
          const { n, svg: heldSvg, carry } = f.drag;
          n.ring.setAttribute('stroke-opacity', '0.75');
          n.fx = null;
          n.fy = null;

          // Land on the pointer before placing.
          //
          // The sim samples the cursor once per frame, so a drag that ends
          // between frames leaves the node wherever the last frame put it —
          // on a fast throw a fraction of the way along, measured at 22% of
          // the distance on a 20-step drag released immediately. The node is
          // placed exactly where it is dropped, so that shortfall would be
          // permanent. The pointerup carries the final position; use it.
          const box = boxFor(heldSvg);
          if (box) {
            n.x = box.vbx + (e.clientX - box.left) / box.sx;
            n.y = box.vby + (e.clientY - box.top) / box.sy;
            clampHeldToViewport(n, box, window.innerHeight);
          }

          // The drop is the point of the whole interaction: a node left
          // somewhere stays there, however short the drag was.
          //
          // The puck carries its concepts. The link force tows them while the
          // drag is live, then stops the instant the puck is placed — so
          // without this their springs walked them back to the original
          // layout and left one edge stretched across the field to a puck
          // that had moved on. A satellite dragged on its own still moves
          // alone; only the puck takes the cluster with it.
          //
          // Rebuilt from the grab-time offsets, NOT from the authored layout
          // and NOT from wherever the tow left them.
          //
          // The authored svg is the wrong picture: the link force's 34-86px
          // rest lengths settle a cluster tighter than it was drawn — 48/48/
          // 50px on screen against 67/130/64px authored — so re-seating the
          // concepts on their home coordinates pops the cluster open at the
          // instant of the drop. Their live positions are the wrong picture
          // too, because a flick outruns the tow.
          //
          // Placing them is what makes it hold. An unplaced concept is still
          // in the charge and collide loops with its siblings but has lost
          // the link force that used to balance them, so it creeps outward —
          // measured drifting 74/113/72px to 96/135/120px over 5s. Placed,
          // the whole cluster is out of the simulation and simply stays.
          n.placed = true;
          n.hx = n.x;
          n.hy = n.y;
          for (const c of carry) {
            c.q.placed = true;
            c.q.x = n.x + c.dx;
            c.q.y = n.y + c.dy;
            c.q.hx = c.q.x;
            c.q.hy = c.q.y;
            c.q.vx = 0;
            c.q.vy = 0;
          }
          n.vx = 0;
          n.vy = 0;

          try { heldSvg.releasePointerCapture(e.pointerId); } catch { /* already released */ }
          heldSvg.style.cursor = 'grab';
          f.drag = null;
          f.target = 0;
        };

        svg.addEventListener('pointerdown', onDown);
        svg.addEventListener('pointermove', onMove);
        window.addEventListener('pointermove', onMove);
        svg.addEventListener('pointerup', up);
        svg.addEventListener('pointercancel', up);
        window.addEventListener('pointerup', up);
        window.addEventListener('pointercancel', up);

        cleanups.push(() => {
          svg.removeEventListener('pointerdown', onDown);
          svg.removeEventListener('pointermove', onMove);
          window.removeEventListener('pointermove', onMove);
          svg.removeEventListener('pointerup', up);
          svg.removeEventListener('pointercancel', up);
          window.removeEventListener('pointerup', up);
          window.removeEventListener('pointercancel', up);
        });
      });
    });
  }

  /**
   * Keeps the held node inside the viewport, and nothing else.
   *
   * This replaced a clamp to the svg's own viewBox, which put invisible walls
   * ~900px sideways and ~1600px up/down of a cluster's home: a node dragged
   * toward the far edge of a wide viewport simply stopped, and a node carried
   * across the page (see `edgeAutoscroll`) stopped a screen and a half in.
   * The viewBox is a paint box, not a play area, so it has no business
   * bounding the drag.
   *
   * Only the pointer-pinned node is clamped. Free nodes are left unbounded on
   * purpose — the anchor spring already pulls every one of them home, so a
   * bound there can only do harm: it would snap a node the moment it was
   * dropped somewhere the spring hadn't reached yet.
   */
  function clampHeldToViewport(p: SimNode, b: ClusterBox, vh: number): void {
    const pad = p.r + 4;
    const xLo = b.vbx + (pad - b.left) / b.sx;
    const xHi = b.vbx + (window.innerWidth - pad - b.left) / b.sx;
    const yLo = b.vby + (pad - b.top) / b.sy;
    const yHi = b.vby + (vh - pad - b.top) / b.sy;
    if (xLo <= xHi) p.x = Math.min(Math.max(p.x, xLo), xHi);
    if (yLo <= yHi) p.y = Math.min(Math.max(p.y, yLo), yHi);
  }

  /**
   * Scrolls the page while a node is dragged into the top or bottom band.
   *
   * Runs before `syncClusters()` so the rects read this frame already include
   * the scroll — deferring it a frame shows up as the cluster juddering
   * against the page.
   */
  function edgeAutoscroll(f: SimGroup, vh: number): void {
    if (!f.drag) return;
    const y = f.drag.cy;
    let k = 0;
    if (y < EDGE_BAND_PX) k = -(1 - y / EDGE_BAND_PX);
    else if (y > vh - EDGE_BAND_PX) k = 1 - (vh - y) / EDGE_BAND_PX;
    if (!k) return;
    window.scrollBy(0, Math.max(-1, Math.min(1, k)) * EDGE_SPEED_PX);
  }

  function stepGroup(f: SimGroup, vh: number, t: number): void {
    const n = f.nodes;
    const L = f.links;
    const a = Math.max(f.alpha, 0.03);
    const held = f.drag ? boxFor(f.drag.svg) : null;

    // link force — heavier strokes want to sit closer and pull harder.
    // A placed node is out of it entirely: the edge still draws to wherever
    // it was left, it just no longer reels it in.
    for (const l of L) {
      const s0 = n[l.a];
      const t0 = n[l.b];
      if (!s0 || !t0 || s0.placed || t0.placed) continue;
      let dx = t0.x - s0.x;
      let dy = t0.y - s0.y;
      const d = Math.hypot(dx, dy) || 0.001;
      const want = 34 + (1 - l.s) * 52;
      const k = ((d - want) / d) * a * (0.15 + l.s * 0.4);
      dx *= k;
      dy *= k;
      // split the correction by inverse radius, so big nodes move less
      const ws = t0.r / (s0.r + t0.r);
      const wt = s0.r / (s0.r + t0.r);
      t0.vx -= dx * wt; t0.vy -= dy * wt;
      s0.vx += dx * ws; s0.vy += dy * ws;
    }

    // charge + collide, within a cluster only
    for (let i = 0; i < n.length; i++) {
      for (let j = i + 1; j < n.length; j++) {
        const p = n[i];
        const q = n[j];
        if (p.cluster !== q.cluster || p.placed || q.placed) continue;
        let dx = q.x - p.x;
        let dy = q.y - p.y;
        let d2 = dx * dx + dy * dy;
        if (d2 < 1) { d2 = 1; dx = 0.6; dy = 0.6; }
        const f2 = ((p.charge + q.charge) * 0.5 * a) / d2;
        q.vx += dx * f2; q.vy += dy * f2;
        p.vx -= dx * f2; p.vy -= dy * f2;
        const d = Math.sqrt(d2);
        const min = p.collide + q.collide;
        if (d < min) {
          const push = ((min - d) / d) * 0.35;
          q.vx += dx * push; q.vy += dy * push;
          p.vx -= dx * push; p.vy -= dy * push;
        }
      }
    }

    for (const p of n) {
      // A slow breathing drift keeps it alive when nothing is being dragged.
      // Not for a placed node: the drift is a ~20px excursion over its 15s
      // period, which is exactly the amount of wandering "it stays where I
      // put it" rules out.
      const idle = f.drag || p.placed ? 0 : 1;
      p.vx += Math.sin(t * 0.00042 + p.hx * 0.05) * 0.06 * idle;
      p.vy += Math.cos(t * 0.00037 + p.hy * 0.05) * 0.06 * idle;
      p.vx += (p.hx - p.x) * 0.012 * a;
      p.vy += (p.hy - p.y) * 0.012 * a;
      if (p.fx != null) { p.x = p.fx; p.vx = 0; } else { p.vx *= 0.6; p.x += p.vx; }
      if (p.fy != null) { p.y = p.fy; p.vy = 0; } else { p.vy *= 0.6; p.y += p.vy; }
      if (!isFinite(p.x) || !isFinite(p.y)) { p.x = p.hx; p.y = p.hy; p.vx = 0; p.vy = 0; }
      if (held && f.drag && p === f.drag.n) clampHeldToViewport(p, held, vh);
      p.ring.setAttribute('cx', p.x.toFixed(1));
      p.ring.setAttribute('cy', p.y.toFixed(1));
      p.glow.setAttribute('cx', p.x.toFixed(1));
      p.glow.setAttribute('cy', p.y.toFixed(1));
      p.label.setAttribute('x', p.x.toFixed(1));
      p.label.setAttribute('y', (p.y + p.ly).toFixed(1));
    }

    for (const l of L) {
      const s0 = n[l.a];
      const t0 = n[l.b];
      if (!s0 || !t0) continue;
      l.el.setAttribute('x1', s0.x.toFixed(1));
      l.el.setAttribute('y1', s0.y.toFixed(1));
      l.el.setAttribute('x2', t0.x.toFixed(1));
      l.el.setAttribute('y2', t0.y.toFixed(1));
    }

    // linear ramp toward target, not d3's exponential decay
    f.alpha += (f.target - f.alpha) * 0.02;
  }

  function step(vh: number, t: number): void {
    if (!groups) return;
    // before syncClusters(), so this frame's rects already carry the scroll
    for (const f of groups) edgeAutoscroll(f, vh);
    // must run before the visibility test below — that test reads cluster
    // rects, which are only correct once this frame's transforms are applied
    syncClusters();
    // The clock can run backwards by a frame here: a scroll event that lands
    // after `t` was stamped makes this negative, which still reads as
    // scrolling. That is the safe direction to be wrong in.
    const scrolling = t - lastScrollAt < SCROLL_QUIET_MS;
    for (const f of groups) {
      let anyVisible = false;
      for (const cl of f.clusters) {
        const b = cl.getBoundingClientRect();
        if (b.bottom > -900 && b.top < vh + 900) { anyVisible = true; break; }
      }
      // re-resolve the held node against the cursor's screen position after
      // the anchors move, so dragging survives a scroll underneath it
      if (f.drag && f.drag.svg) {
        const svg = f.drag.svg;
        const r = svg.getBoundingClientRect();
        const vb = svg.viewBox.baseVal;
        if (r.width) {
          const kx = vb && vb.width ? vb.width / r.width : 1;
          const ky = vb && vb.height ? vb.height / r.height : 1;
          f.drag.n.fx = (vb ? vb.x : 0) + (f.drag.cx - r.left) * kx;
          f.drag.n.fy = (vb ? vb.y : 0) + (f.drag.cy - r.top) * ky;
        }
      }
      // Frozen mid-scroll unless this group holds the pointer: `syncClusters()`
      // has already translated it with its section, and any integration on top
      // of that is motion the page didn't ask for.
      if (scrolling && !f.drag) continue;
      if (anyVisible || f.drag) stepGroup(f, vh, t);
    }
  }

  function destroy(): void {
    cleanups.forEach((fn) => fn());
    cleanups.length = 0;
    anchors.length = 0;
    groups = null;
    lastScrollAt = -Infinity;
    if (overlay && overlay.parentElement) overlay.parentElement.removeChild(overlay);
    overlay = null;
  }

  return { ensureInit, step, destroy };
}
