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
 * Writes `cx`/`cy` straight onto the SVG elements. No React, no canvas.
 */

const OVERLAY_CLASS = 'drag-overlay';

interface SimNode {
  /** viewBox-derived bounds, so nodes can't be dragged out of their svg. */
  bx: number; by: number; xMax: number; yMax: number;
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
}

interface SimLink {
  a: number;
  b: number;
  el: SVGLineElement;
  /** Normalised stroke weight, 0..1 — heavier links sit closer. */
  s: number;
}

interface SimGroup {
  field: HTMLElement;
  clusters: HTMLElement[];
  nodes: SimNode[];
  links: SimLink[];
  alpha: number;
  target: number;
  drag: { n: SimNode; id: number; svg: SVGSVGElement; cx: number; cy: number } | null;
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
  const cleanups: (() => void)[] = [];

  function ensureInit(root: HTMLElement): boolean {
    if (groups) return true;
    const fields = Array.from(root.querySelectorAll<HTMLElement>('.drag-field'));
    if (!fields.length) return false;
    // hidden below 1024px by the media query — don't build it at all
    if (getComputedStyle(fields[0]).display === 'none') return false;

    if (!overlay) {
      overlay = document.createElement('div');
      overlay.className = OVERLAY_CLASS;
      overlay.setAttribute('aria-hidden', 'true');
      overlay.style.cssText =
        'position:absolute; top:0; left:0; width:100%; height:0; z-index:45; pointer-events:none; overflow:visible;';
      root.appendChild(overlay);
    }

    const built: SimGroup[] = [];
    fields.forEach((field) => {
      const clusters = Array.from(field.querySelectorAll<HTMLElement>('[data-dragnode]'));
      if (!clusters.length) return;

      // remember where each cluster sat on the page, then re-home it in the
      // overlay so its parts can travel outside the section's bounds
      clusters.forEach((cl) => {
        const ob = overlay!.getBoundingClientRect();
        const b = cl.getBoundingClientRect();
        const anchor = { left: b.left - ob.left, top: b.top - ob.top };
        cl.style.animation = 'none';
        cl.style.position = 'absolute';
        cl.style.left = anchor.left.toFixed(1) + 'px';
        cl.style.top = anchor.top.toFixed(1) + 'px';
        cl.style.right = 'auto';
        cl.style.bottom = 'auto';
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
          const vbn = svg.viewBox.baseVal;
          nodes.push({
            bx: vbn ? -vbn.x : 150, by: vbn ? -vbn.y : 400,
            xMax: vbn ? vbn.x + vbn.width : 300, yMax: vbn ? vbn.y + vbn.height : 300,
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
          f.drag = { n, id: e.pointerId, svg, cx: e.clientX, cy: e.clientY };
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
          f.drag.n.ring.setAttribute('stroke-opacity', '0.75');
          f.drag.n.fx = null;
          f.drag.n.fy = null;
          try { svg.releasePointerCapture(e.pointerId); } catch { /* already released */ }
          svg.style.cursor = 'grab';
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

  function stepGroup(f: SimGroup, t: number): void {
    const n = f.nodes;
    const L = f.links;
    const a = Math.max(f.alpha, 0.03);

    // link force — heavier strokes want to sit closer and pull harder
    for (const l of L) {
      const s0 = n[l.a];
      const t0 = n[l.b];
      if (!s0 || !t0) continue;
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
        if (p.cluster !== q.cluster) continue;
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
      // a slow breathing drift keeps it alive when nothing is being dragged
      const idle = f.drag ? 0 : 1;
      p.vx += Math.sin(t * 0.00042 + p.hx * 0.05) * 0.06 * idle;
      p.vy += Math.cos(t * 0.00037 + p.hy * 0.05) * 0.06 * idle;
      p.vx += (p.hx - p.x) * 0.012 * a;
      p.vy += (p.hy - p.y) * 0.012 * a;
      if (p.fx != null) { p.x = p.fx; p.vx = 0; } else { p.vx *= 0.6; p.x += p.vx; }
      if (p.fy != null) { p.y = p.fy; p.vy = 0; } else { p.vy *= 0.6; p.y += p.vy; }
      if (!isFinite(p.x) || !isFinite(p.y)) { p.x = p.hx; p.y = p.hy; p.vx = 0; p.vy = 0; }
      p.x = Math.max(-p.bx + p.r, Math.min(p.xMax - p.r, p.x));
      p.y = Math.max(-p.by + p.r, Math.min(p.yMax - p.r, p.y));
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
      if (anyVisible || f.drag) stepGroup(f, t);
    }
  }

  function destroy(): void {
    cleanups.forEach((fn) => fn());
    cleanups.length = 0;
    groups = null;
    if (overlay && overlay.parentElement) overlay.parentElement.removeChild(overlay);
    overlay = null;
  }

  return { ensureInit, step, destroy };
}
