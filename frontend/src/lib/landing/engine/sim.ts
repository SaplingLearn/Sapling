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
 * dropped somewhere is *placed*, and holds that spot. See `SimNode.placed`.
 *
 * Above all of it sits `holdArms()`, a hard ceiling on every arm's length.
 * The forces decide how a cluster settles and breathes; the ceiling decides
 * what it can never do, which is stretch. That split is deliberate — a spring
 * can only ever answer a gap with a fraction of the correction, so no amount
 * of tuning makes one promise a maximum.
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

/**
 * How much of the idle breathing drift a placed node keeps.
 *
 * A free node traces a ~20px excursion over its 15s period. A node the
 * visitor put somewhere should still be breathing — dropping one used to kill
 * it stone dead, which reads as a bug rather than as precision — but at the
 * full amplitude it looks like it is wandering off rather than sitting where
 * it was left. A third is the compromise: a few px of life, well inside the
 * radius anyone would call "where I put it".
 */
const PLACED_SWAY = 0.33;

/**
 * Anchor-spring gain for a placed node, holding it to the spot it was left.
 *
 * Fixed rather than scaled by alpha, and ~8x the free spring's settled gain.
 * The two numbers work together: `PLACED_SWAY` decides how hard the node is
 * pushed, this decides how far that push gets it, and their ratio is the
 * excursion. Around 7px at these values.
 */
const PLACED_ANCHOR = 0.003;


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
   * choosing.
   *
   * A placed node holds that spot: it takes no recoil from the link, charge
   * or collide forces, and breathes at a reduced amplitude around it. It is
   * not removed from those forces — it still acts on its neighbours, which is
   * what makes a cluster react to one of its nodes being moved.
   *
   * Nor is it immovable. `holdArms()` will drag a placed node to keep an arm
   * within its length, because two nodes placed further apart than their arm
   * is long is a request that cannot be met, and a stretched arm is the more
   * visible wrong answer.
   */
  placed: boolean;
}

interface SimLink {
  a: number;
  b: number;
  el: SVGLineElement;
  /** Normalised stroke weight, 0..1 — heavier links sit closer. */
  s: number;
  /**
   * The arm's length as the cluster was drawn, and the length it keeps.
   *
   * Both the spring's rest length and the hard ceiling `holdArms()` enforces.
   * Taken from the authored geometry rather than computed from stroke weight
   * so a cluster holds the shape it was designed with.
   */
  len: number;
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
  /** Scratch for `holdArms()`: node positions before the solve. Preallocated
   *  so the constraint stays allocation-free on the frame path. */
  armX: number[];
  armY: number[];
  alpha: number;
  target: number;
  drag: {
    n: SimNode; id: number; svg: SVGSVGElement; cx: number; cy: number;
    /** The held svg's screen top last frame, for scroll compensation. */
    boxTop: number | null;
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
  /**
   * The fixed wrapper holding `overlay`.
   *
   * Tracked here rather than through `cleanups` so `destroy()` can remove it
   * *after* every cluster has been re-homed. As a cleanup it was pushed before
   * the clusters were re-parented into it, so it detached them along with
   * itself; see `clusterHomes`.
   */
  let shellEl: HTMLDivElement | null = null;
  /**
   * Where each cluster lived before `ensureInit()` re-parented it into the
   * overlay, so `destroy()` can put it back.
   *
   * Without this, destroy left every `[data-dragnode]` detached from the
   * document: a later `createSim().ensureInit()` found no cluster elements and
   * returned false forever, silently killing the drag field. React StrictMode's
   * dev-mode setup → cleanup → setup on the same DOM hits exactly that.
   */
  const clusterHomes: {
    el: HTMLElement;
    parent: HTMLElement | null;
    next: Element | null;
    /** The cluster's own inline styles before the sim overwrote them. */
    css: string;
  }[] = [];
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
      shellEl = shell;
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
        // Recorded BEFORE the re-parent and before the styles below are
        // overwritten. `destroy()` puts the cluster back at this exact slot
        // with this exact cssText; leaving `position:absolute; left:0; top:0`
        // behind would make the next build measure every anchor against the
        // overlay-parked position instead of the designed one.
        clusterHomes.push({
          el: cl,
          parent: cl.parentElement,
          next: cl.nextElementSibling,
          css: cl.style.cssText,
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

        // The sim binds by sibling order: glow circle, ring, label text. Every
        // one of those three is dereferenced unconditionally on the frame path
        // (`p.glow.setAttribute`, `p.label.setAttribute`), so a ring whose
        // siblings do not match would throw once per frame, forever, killing
        // the whole rAF loop rather than just its own node. Checked by
        // localName rather than `instanceof` so it holds in any DOM impl.
        rings.forEach((ring, ri) => {
          const prev = ring.previousElementSibling;
          const next = ring.nextElementSibling;
          if (prev?.localName !== 'circle' || next?.localName !== 'text') return;
          const glow = prev as SVGCircleElement;
          const label = next as SVGTextElement;
          const r = parseFloat(ring.getAttribute('r') || '0');
          nodes.push({
            x: parseFloat(ring.getAttribute('cx') || '0'),
            y: parseFloat(ring.getAttribute('cy') || '0'),
            vx: 0, vy: 0, fx: null, fy: null, r,
            root: ri === 0, cluster: ci,
            // the root sits heavier and pushes harder than its satellites.
            // Radii mirror the real graph's forceCollide: 36 for a subject
            // root, 18 upward for everything else.
            collide: ri === 0 ? 36 : 18 + r * 0.5,
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
          // `near()` returns -1 when this cluster contributed no nodes — an svg
          // with <line>s but no [data-sim] rings, or rings the guard above
          // rejected. `len` below indexes `nodes[a]`/`nodes[b]` immediately, so
          // an unmatched end has to be dropped here rather than deferred to the
          // `if (!s0 || !t0) continue;` guard on the frame path.
          if (a < 0 || b < 0) return;
          links.push({
            a, b, el: ln,
            s: (parseFloat(ln.getAttribute('stroke-width') || '0.5') - 0.5) / 1.2,
            len: Math.hypot(nodes[b].x - nodes[a].x, nodes[b].y - nodes[a].y) || 1,
          });
        });

        // the cluster no longer floats as a unit; the sim moves its parts
        cl.style.animation = 'none';
        const puck = cl.querySelector<HTMLElement>('[data-dragpuck]');
        if (puck) puck.style.transform = 'none';
        svg.style.overflow = 'visible';
      });

      nodes.forEach((n) => { n.hx = n.x; n.hy = n.y; });
      built.push({
        field, clusters, nodes, links, alpha: 1, target: 0, drag: null,
        armX: new Array<number>(nodes.length).fill(0),
        armY: new Array<number>(nodes.length).fill(0),
      });
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
          f.drag = { n, id: e.pointerId, svg, cx: e.clientX, cy: e.clientY, boxTop: null };
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
          const { n, svg: heldSvg } = f.drag;
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
          }

          // The drop is the point of the whole interaction: a node left
          // somewhere stays there, however short the drag was.
          //
          // ONLY this node. Placing its whole cluster held the shape, but it
          // took every one of them out of the simulation, so after a single
          // drag the field was dead — no sway, no reaction to anything. The
          // cluster keeps its shape now because a placed node still anchors
          // the link force (see `stepGroup`), so its concepts are drawn back
          // to rest length around wherever it landed instead of being frozen
          // into position.
          n.placed = true;
          n.vx = 0;
          n.vy = 0;

          // The cluster's rest position is wherever the drag left it.
          //
          // Only this node is placed — its neighbours stay free, and keep
          // their full sway — but every one of them is re-homed here. Without
          // that their anchor springs still point at the layout the page
          // loaded with, so the cluster walks back to it and, since the arms
          // are hard-capped, hauls the node the visitor just placed along
          // with it: measured dragging a dropped node 515px back across the
          // field over 1200 frames. The arm ceiling and a home the cluster
          // has already left cannot both be honoured; the drop is the more
          // recent instruction.
          for (const q of f.nodes) {
            if (q.cluster !== n.cluster) continue;
            q.hx = q.x;
            q.hy = q.y;
          }

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
   * Cancel the page's scroll out of the held cluster's coordinates.
   *
   * A scroll is a camera move and must not read as a force. The cluster is
   * welded to its field, so it travels with the page, while the held node is
   * pinned to a pointer that may not have moved at all — and the difference
   * lands on the link spring as relative motion the visitor never made. The
   * edge-band autoscroll pushes 22px of it per frame, every frame, for as
   * long as the node is held there: the spring does not settle at a lag, it
   * diverges. Measured stretching a cluster from 59/104/60px to 243/488/207px
   * over one continuous autoscroll, which is the long branch itself.
   *
   * The delta is read from the cluster's own screen movement rather than from
   * the scroll call, so it is right whoever did the scrolling and whatever
   * order the frame ran in. With it cancelled, the simulation answers only for
   * motion made with the pointer — which is all the real graph ever sees.
   */
  function compensateScroll(f: SimGroup): void {
    if (!f.drag) return;
    const b = boxFor(f.drag.svg);
    if (!b) return;
    const prev = f.drag.boxTop;
    f.drag.boxTop = b.top;
    if (prev == null) return;
    const d = (prev - b.top) / b.sy;
    if (!d) return;
    for (const q of f.nodes) {
      if (q === f.drag.n || q.cluster !== f.drag.n.cluster) continue;
      q.y += d;
      q.hy += d;
    }
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

/**
 * Number of times the arm constraint is swept per frame.
 *
 * One pass fixes each arm in isolation and immediately breaks its neighbour,
 * so a chain of them only converges over several: pulling the far end of
 * `ME 218 - Free-body - Statics` has to travel two arms to reach the puck.
 * Three sweeps left 0.23px on the table dragging a concept, and six left
 * 0.51px with two placed nodes on one arm — invisible either way, but
 * the ceiling is worth stating exactly. Twelve clears it with room to spare
 * and costs nothing: a handful of links, no allocation, no DOM.
 */
const ARM_SWEEPS = 12;

/**
 * Where the link spring rests, as a fraction of the arm's hard ceiling.
 *
 * The two must not coincide. Resting the spring exactly at the ceiling leaves
 * a dragged-out cluster pinned against it: every arm at its limit, every
 * outward breath clipped by `holdArms()` the same frame, and the node sitting
 * dead still however much it is breathing. Resting a little inside gives the
 * sway somewhere to happen — the cluster settles off the ceiling after a drag
 * and only touches it again when something is actually pulling.
 */
const ARM_REST = 0.88;

/**
 * How much of an arm correction is handed back to the node as velocity.
 *
 * `holdArms()` moves positions, and a position moved is a position with no
 * memory: the node is where the arm needs it and travelling at whatever speed
 * it had before, which is usually none. A cluster dragged that way arrives
 * rather than swings — it snaps to the pointer in place, with no follow-
 * through when the pointer stops. Feeding the correction back as velocity is
 * what puts the momentum in, and is the standard closing step of a
 * position-based solve.
 *
 * Well under 1: the full correction reads as overshoot, since the same
 * displacement is then applied twice, once as position and again as the
 * velocity that carries into the next frame.
 */
const ARM_MOMENTUM = 0.55;

/**
 * Share of an arm correction a placed node takes when the other end is free.
 *
 * Small, so a dropped node holds the spot it was left on: splitting the
 * correction evenly hauled one 40px back toward its cluster the moment an arm
 * was over length. Not zero, because an end that never moves cannot resolve
 * an infeasible cluster and leaves an arm stretched instead.
 */
const PLACED_YIELD = 0.12;

  /**
   * Hard ceiling on every arm's length, applied to positions after the forces.
   *
   * The link spring cannot promise this and never could. It is a spring: it
   * answers a gap with a fraction of the correction, so the faster a node is
   * pulled the further the arm gives, and an arm under continuous load just
   * keeps opening. Dragging a concept out of `ME 218` drew its two arms into
   * a line right across the section.
   *
   * A position constraint promises it outright. After integrating, any arm
   * longer than the length it was drawn at is shortened back to it, moving
   * whichever ends are free to move. That is also what carries the cluster:
   * pull one node and the arm reaches its limit, so its neighbour is dragged
   * bodily along, and the sweep passes that on down the chain. It is the same
   * for a concept as for the puck — the constraint has no idea which is which.
   *
   * Only ever shortens. An arm is free to fold up as far as the charge and
   * collide forces allow, which is what leaves the sway intact.
   */
  function holdArms(f: SimGroup): void {
    const n = f.nodes;
    for (let i = 0; i < n.length; i++) { f.armX[i] = n[i].x; f.armY[i] = n[i].y; }
    for (let sweep = 0; sweep < ARM_SWEEPS; sweep++) {
      for (const l of f.links) {
        const s0 = n[l.a];
        const t0 = n[l.b];
        if (!s0 || !t0) continue;
        // Only the node under the pointer is immovable, and the whole
        // correction falls on the other end.
        //
        // A placed node is NOT exempt, though it reads like it should be.
        // Every drop places a node, so after a couple of drags most of a
        // cluster is placed, and an arm between two of them was skipped
        // entirely — nothing could ever shorten it. That is a stretched arm
        // that never recovers: `CS 112 - Memoize` drawn clean across the FAQ
        // while the rest of the cluster sat together at the far end.
        //
        // Two nodes placed further apart than their arm is long is a request
        // that cannot be met. The arm wins: a placed node yields to it rather
        // than holding a shape that was never drawable.
        // How pinned each end is: held by the pointer beats placed by the
        // visitor beats free. The correction falls on the LESS pinned end,
        // entirely — split it and a dropped node gets hauled halfway back to
        // its cluster by every arm that was over length at the drop, 40px off
        // the spot it was left on. Equally pinned ends share it, which is
        // what lets two placed nodes still be pulled together.
        const rs = s0.fx != null ? 2 : (s0.placed ? 1 : 0);
        const rt = t0.fx != null ? 2 : (t0.placed ? 1 : 0);
        if (rs === 2 && rt === 2) continue;
        const dx = t0.x - s0.x;
        const dy = t0.y - s0.y;
        const d = Math.hypot(dx, dy);
        if (d <= l.len || d < 0.001) continue;
        const over = (d - l.len) / d;
        // The correction falls on the less pinned end. A held node never
        // yields at all; a placed one RESISTS rather than refuses, taking
        // PLACED_YIELD of it. Refusing outright looks right and is not:
        // three nodes cannot always satisfy two arms — drag one far enough
        // and the geometry is simply infeasible — and an end that never
        // moves resolves that by leaving an arm stretched, which is the one
        // outcome ruled out. Yielding a little settles it over a few sweeps
        // while still holding the spot for every reachable arrangement.
        let ws: number;
        let wt: number;
        if (rs === rt) {
          ws = 0.5;
          wt = 0.5;
        } else {
          const give = (rs > rt ? s0 : t0).fx != null ? 0 : PLACED_YIELD;
          ws = rs > rt ? give : 1 - give;
          wt = rs > rt ? 1 - give : give;
        }
        // A placed node's home comes with it. Leaving the home behind puts
        // its anchor spring against the constraint every frame — the spring
        // hauling it back to a spot the arm cannot reach — and the node sits
        // shuddering between the two.
        if (ws) {
          s0.x += dx * over * ws;
          s0.y += dy * over * ws;
          if (s0.placed) { s0.hx += dx * over * ws; s0.hy += dy * over * ws; }
        }
        if (wt) {
          t0.x -= dx * over * wt;
          t0.y -= dy * over * wt;
          if (t0.placed) { t0.hx -= dx * over * wt; t0.hy -= dy * over * wt; }
        }
      }
    }

    // Hand the solve's displacement back as velocity, so a node dragged by
    // its arm carries on moving instead of arriving dead. See ARM_MOMENTUM.
    //
    // Free nodes only. The held one is pinned and about to have its velocity
    // cleared anyway; a placed one is supposed to hold its spot, and follow-
    // through is the opposite of that — handing it momentum walked a dropped
    // node 32px off the point it was left on, well outside its sway. It still
    // yields to the arm, it just does not coast afterwards.
    for (let i = 0; i < n.length; i++) {
      const p = n[i];
      if (p.fx != null || p.placed) continue;
      p.vx += (p.x - f.armX[i]) * ARM_MOMENTUM;
      p.vy += (p.y - f.armY[i]) * ARM_MOMENTUM;
    }
  }

  function stepGroup(f: SimGroup, vh: number, t: number): void {
    const n = f.nodes;
    const L = f.links;
    const a = Math.max(f.alpha, 0.03);
    // Before any force runs: take the page's own scroll back out of the held
    // cluster, so the springs only see what the pointer did.
    compensateScroll(f);

    // link force — heavier strokes want to sit closer and pull harder.
    //
    // A placed node ANCHORS rather than dropping out: it still pulls on the
    // other end, it just never moves itself. That is the whole reason a
    // cluster reacts to one of its nodes being moved — drag a concept and the
    // puck and its siblings swing after it, drop the puck and its concepts
    // gather back to rest length around wherever it landed. Skipping the link
    // entirely, as this used to, is what left a placed node trailing a long
    // dead edge and the rest of the cluster sitting perfectly still.
    for (const l of L) {
      const s0 = n[l.a];
      const t0 = n[l.b];
      if (!s0 || !t0) continue;
      // Two anchors have nothing to say to each other.
      if (s0.placed && t0.placed) continue;
      let dx = t0.x - s0.x;
      let dy = t0.y - s0.y;
      const d = Math.hypot(dx, dy) || 0.001;
      // Strength is the real graph's, verbatim — `KnowledgeGraph2D` builds the
      // same d3 force with `.strength(0.15 + strength * 0.4)`. The rest length
      // is NOT: the graph derives one from stroke weight because it lays its
      // own nodes out, while these clusters were drawn by hand and the arm
      // lengths are the drawing. It rests just inside the ceiling `holdArms()`
      // enforces, never at it — see ARM_REST.
      const want = l.len * ARM_REST;
      const k = ((d - want) / d) * a * (0.15 + l.s * 0.4);
      dx *= k;
      dy *= k;
      // Split the correction by inverse radius, so big nodes move less —
      // except against an anchor, which absorbs none of it, so the free end
      // takes the whole correction and actually closes the gap.
      const ws = t0.placed ? 1 : t0.r / (s0.r + t0.r);
      const wt = s0.placed ? 1 : s0.r / (s0.r + t0.r);
      if (!t0.placed) { t0.vx -= dx * wt; t0.vy -= dy * wt; }
      if (!s0.placed) { s0.vx += dx * ws; s0.vy += dy * ws; }
    }

    // charge + collide, within a cluster only
    for (let i = 0; i < n.length; i++) {
      for (let j = i + 1; j < n.length; j++) {
        const p = n[i];
        const q = n[j];
        // Same anchor rule as the link force: a placed node still pushes on
        // its neighbours, it just does not take the recoil.
        if (p.cluster !== q.cluster || (p.placed && q.placed)) continue;
        let dx = q.x - p.x;
        let dy = q.y - p.y;
        let d2 = dx * dx + dy * dy;
        if (d2 < 1) { d2 = 1; dx = 0.6; dy = 0.6; }
        const f2 = ((p.charge + q.charge) * 0.5 * a) / d2;
        if (!q.placed) { q.vx += dx * f2; q.vy += dy * f2; }
        if (!p.placed) { p.vx -= dx * f2; p.vy -= dy * f2; }
        const d = Math.sqrt(d2);
        const min = p.collide + q.collide;
        if (d < min) {
          const push = ((min - d) / d) * 0.35;
          if (!q.placed) { q.vx += dx * push; q.vy += dy * push; }
          if (!p.placed) { p.vx -= dx * push; p.vy -= dy * push; }
        }
      }
    }

    for (const p of n) {
      // A slow breathing drift keeps every node alive — the sway.
      //
      // A placed node breathes too, at `PLACED_SWAY` of the amplitude. It
      // used to be cut to nothing, on the reading that "it stays where I put
      // it" ruled out any wandering at all; what that actually bought was a
      // node that went dead the instant it was dropped, which is worse. The
      // anchor spring still holds it to the spot it was put — the sway is an
      // excursion around that point, not a walk away from it — so at a third
      // of the free amplitude it reads as alive and still lands where it was
      // left. Only the node under the pointer is held perfectly still, and
      // only while it is held.
      const idle = f.drag && p === f.drag.n ? 0 : (p.placed ? PLACED_SWAY : 1);
      p.vx += Math.sin(t * 0.00042 + p.hx * 0.05) * 0.06 * idle;
      p.vy += Math.cos(t * 0.00037 + p.hy * 0.05) * 0.06 * idle;
      // A placed node is tethered harder than a free one, and at a fixed gain
      // rather than one that fades with alpha.
      //
      // Its excursion is roughly `breathing impulse / spring gain`, and the
      // free spring settles to `0.012 * 0.03` — weak enough that the same
      // breathing walks a placed node right off its spot: measured drifting
      // 3.6px to 17px over 8.4s and still climbing, which is not a sway, it
      // is a departure. PLACED_ANCHOR holds the excursion near 7px, so the
      // node breathes around where it was left instead of leaving.
      const springK = p.placed ? PLACED_ANCHOR : 0.012 * a;
      p.vx += (p.hx - p.x) * springK;
      p.vy += (p.hy - p.y) * springK;
      if (p.fx != null) { p.x = p.fx; p.vx = 0; } else { p.vx *= 0.6; p.x += p.vx; }
      if (p.fy != null) { p.y = p.fy; p.vy = 0; } else { p.vy *= 0.6; p.y += p.vy; }
      if (!isFinite(p.x) || !isFinite(p.y)) { p.x = p.hx; p.y = p.hy; p.vx = 0; p.vy = 0; }
    }

    holdArms(f);

    for (const p of n) {
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
    // Re-home every cluster FIRST. The shell is removed below, and the
    // clusters live inside it by now — dropping the shell with them still
    // attached detached them from the document permanently, so the next
    // `ensureInit()` found no `[data-dragnode]` and returned false forever.
    for (let i = clusterHomes.length - 1; i >= 0; i--) {
      const h = clusterHomes[i];
      h.el.style.cssText = h.css;
      // `next` may itself have been re-parented into the overlay, in which
      // case it is no longer a child of `parent`; insertBefore would throw.
      // Appending is the correct fallback — the clusters are absolutely
      // positioned decoration, so DOM order among them carries no meaning.
      if (!h.parent) continue;
      if (h.next && h.next.parentElement === h.parent) h.parent.insertBefore(h.el, h.next);
      else h.parent.appendChild(h.el);
    }
    clusterHomes.length = 0;
    anchors.length = 0;
    groups = null;
    lastScrollAt = -Infinity;
    shellEl?.remove();
    shellEl = null;
    overlay = null;
  }

  return { ensureInit, step, destroy };
}
