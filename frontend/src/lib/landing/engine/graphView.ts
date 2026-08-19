/**
 * Act I: the projected 3D knowledge graph, and the explore mode it opens into.
 *
 * Ported from `Sapling Landing v4.dc.html`. Both views draw the *same* graph
 * with the same projection; they differ only in where the camera sits and
 * what drives the reveal.
 *
 *  - `drawScroll(p)`   scroll-driven. Nodes spawn and turn from grey to their
 *                      tier colour as `p` passes their baked-in thresholds.
 *  - `drawExplore()`   user-driven. Picks the camera up exactly where
 *                      `drawScroll` left it (`camSnap`) and *continues* each
 *                      node's reveal from wherever it had got to, rather than
 *                      restarting — which is why entering explore mid-scroll
 *                      doesn't flash.
 *
 * Perspective is a plain divide (`fl / (fl + z)`) with painter's-algorithm
 * depth sorting. Deliberately not WebGL: matching the source's exact node
 * edges and label metrics matters more than the throughput here.
 */

import { clamp01, lerpColor, smooth } from '../color';
import { XTIER_LABEL } from '../course';
import { cv } from './dom';
import type { BuiltGraph, GraphNode } from './graph';

/** Focal length for the perspective divide. */
const FL = 1050;
/** The grey every node starts as, before its tier colour bleeds in. */
const GREY = '#7d8a84';

export interface Cam {
  rotY: number;
  rotX: number;
  zoom: number;
  cx: number;
  cy: number;
}

export interface Projected {
  x: number;
  y: number;
  z: number;
  /** Projection scale at this depth. */
  sc: number;
  n: GraphNode;
  i: number;
}

export interface GraphViewState {
  /** Free-orbit offsets, driven by pointer drag. */
  orbX: number;
  orbY: number;
  actMouse: { x: number; y: number } | null;
  /** Where the scroll camera last was — explore mode starts from here. */
  camSnap: Cam | null;
  lastP: number;

  // explore
  expT0: number;
  /** True while playing the exit transition backwards. */
  expOut: boolean;
  expZoom: number;
  camFrom: Cam | null;
  /** Per-node colour/spawn progress captured at the moment explore opened. */
  expCpFrom: number[] | null;
  expSpFrom: number[] | null;
  /** Radial stagger, 0..1 by distance from centre. */
  expOrder: number[] | null;
  expProj: Projected[] | null;
  expHover: number | null;
}

export function createGraphViewState(): GraphViewState {
  return {
    orbX: 0, orbY: 0, actMouse: null, camSnap: null, lastP: 0,
    expT0: 0, expOut: false, expZoom: 1, camFrom: null,
    expCpFrom: null, expSpFrom: null, expOrder: null,
    expProj: null, expHover: null,
  };
}

/**
 * Snapshot the camera and each node's reveal progress so explore mode can
 * continue them rather than restart. Call before flipping into explore.
 */
export function beginExplore(st: GraphViewState, graph: BuiltGraph): void {
  st.expZoom = 1;
  st.expOut = false;
  st.expT0 = performance.now();
  const t = Date.now() * 0.001;
  const cam = st.camSnap;
  if (cam) {
    // subtract the auto-spin so the camera doesn't jump on handover
    st.orbY = cam.rotY - t * 0.035;
    st.orbX = cam.rotX;
    st.camFrom = cam;
  } else {
    st.orbY = 0.2;
    st.orbX = -0.06;
    st.camFrom = null;
  }
  const p = st.lastP || 0;
  st.expCpFrom = graph.nodes.map((n) => clamp01(smooth((p - n.colorAt) / 0.16)));
  st.expSpFrom = graph.nodes.map((n) => clamp01(smooth((p - n.spawnAt) / 0.05)));
  // stagger by graph distance from the centre so the fill radiates outward
  st.expOrder = graph.nodes.map((n) => clamp01(Math.hypot(n.ox, n.oy, n.oz) / 620));
}

/** Start the exit transition (the draw runs `expT0` backwards). */
export function beginExitExplore(st: GraphViewState): void {
  st.expOut = true;
  st.expT0 = performance.now();
}

/** Hand the camera back to the scroll view once the exit has played out. */
export function settleExitExplore(st: GraphViewState): void {
  st.expOut = false;
  const t = Date.now() * 0.001;
  const p = st.lastP || 1;
  st.orbY = st.orbY + t * 0.035 - 0.25 - p * 1.15 - t * 0.02;
  st.orbX = st.orbX + 0.12;
}

/** Nearest node within 28px of a point, or null. */
export function pickNode(st: GraphViewState, pt: { x: number; y: number } | null): Projected | null {
  if (!pt || !st.expProj) return null;
  let best = 28;
  let hit: Projected | null = null;
  st.expProj.forEach((pr) => {
    const d = Math.hypot(pr.x - pt.x, pr.y - pt.y);
    if (d < best) {
      best = d;
      hit = pr;
    }
  });
  return hit;
}

/** ── scroll-driven view ─────────────────────────────────────────────── */
export function drawScroll(
  canvas: HTMLCanvasElement,
  graph: BuiltGraph,
  st: GraphViewState,
  p: number,
): void {
  const c = cv(canvas);
  const { ctx, w, h } = c;
  ctx.clearRect(0, 0, w, h);

  const { nodes, edges } = graph;
  const t = Date.now() * 0.001;
  // the frame drifts left late on, making room for the closing caption
  const cx = w * (0.58 - 0.08 * smooth((p - 0.6) / 0.2));
  const cy = h * 0.48;
  const rotY = 0.25 + p * 1.15 + st.orbY + t * 0.02;
  const rotX = -0.12 + st.orbX;
  const zoomIn = 0.8 + 0.25 * smooth(p / 0.12);
  const pull = 1 - 0.22 * smooth((p - 0.74) / 0.22);
  const zoom = zoomIn * pull;

  const cosY = Math.cos(rotY), sinY = Math.sin(rotY);
  const cosX = Math.cos(rotX), sinX = Math.sin(rotX);
  const proj: Projected[] = nodes.map((n, i) => {
    const wob = Math.sin(t * 0.5 + n.seed) * 10;
    const x = n.ox * cosY - n.oz * sinY;
    const z = n.oz * cosY + n.ox * sinY;
    const y = (n.oy + wob) * cosX - z * sinX * 0.4;
    const sc = (FL / (FL + z)) * zoom;
    return { x: x * sc + cx, y: y * sc + cy, z, sc, n, i };
  });

  // edges draw as a growing line from a to b
  edges.forEach((e) => {
    const ep = smooth((p - e.drawAt) / 0.07);
    if (ep <= 0) return;
    const a = proj[e.a], b = proj[e.b];
    const ex = a.x + (b.x - a.x) * ep;
    const ey = a.y + (b.y - a.y) * ep;
    const alpha = 0.16 * Math.min(1, a.sc) * (1 + 0.4 * smooth((p - 0.82) / 0.14));
    ctx.strokeStyle = 'rgba(143,217,168,' + alpha.toFixed(3) + ')';
    ctx.lineWidth = 0.7;
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(ex, ey);
    ctx.stroke();
  });

  let hover: Projected | null = null;
  if (st.actMouse && p > 0.2) {
    let best = 26;
    proj.forEach((pr) => {
      const d = Math.hypot(pr.x - st.actMouse!.x, pr.y - st.actMouse!.y);
      if (d < best) { best = d; hover = pr; }
    });
  }

  proj
    .slice()
    .sort((a, b) => b.z - a.z)
    .forEach((pr) => {
      const n = pr.n;
      const sp = smooth((p - n.spawnAt) / 0.05);
      if (sp <= 0) return;
      const cp = smooth((p - n.colorAt) / 0.16);
      const color = cp <= 0 ? GREY : cp >= 1 ? n.final : lerpColor(GREY, n.final, cp);
      const breathe = 0.92 + 0.08 * Math.sin(t * 0.7 + n.seed);
      const fog = pr.z > 400 ? Math.max(0.15, 1 - (pr.z - 400) / 700) : 1;
      // overshoot slightly while spawning, so nodes pop rather than fade
      let r = n.r * pr.sc * breathe * (sp < 1 ? (1.4 - 0.4 * sp) * sp : 1);
      if (hover === pr) r *= 1.6;
      if (r < 0.2) return;
      ctx.globalAlpha = fog * Math.min(1, sp * 1.4);
      ctx.beginPath();
      ctx.arc(pr.x, pr.y, r, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
      if (n.hub && cp > 0.35) {
        ctx.globalAlpha = 0.25 * fog * smooth((cp - 0.35) / 0.4);
        ctx.beginPath();
        ctx.arc(pr.x, pr.y, r + 6, 0, Math.PI * 2);
        ctx.strokeStyle = color;
        ctx.lineWidth = 1;
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
    });

  if (p > 0.76) {
    const la = smooth((p - 0.76) / 0.1);
    ctx.font = '11px "JetBrains Mono", monospace';
    proj.forEach((pr) => {
      if (!pr.n.hub) return;
      ctx.globalAlpha = la * 0.85;
      ctx.fillStyle = '#B9D9C4';
      ctx.fillText(pr.n.label.toUpperCase(), pr.x + 14, pr.y + 4);
    });
    ctx.globalAlpha = 1;
  }

  st.camSnap = { rotY, rotX, zoom, cx, cy };
  st.lastP = p;

  // hover chip — concepts only; hubs already carry a permanent label
  const hv = hover as Projected | null;
  if (hv && !hv.n.hub) {
    const cp = smooth((p - hv.n.colorAt) / 0.09);
    const status = cp < 0.05 ? 'UNEXPLORED' : XTIER_LABEL[hv.n.tier].toUpperCase();
    const label = hv.n.label;
    ctx.font = '600 12px "DM Sans", sans-serif';
    const tw = ctx.measureText(label).width;
    ctx.font = '9px "JetBrains Mono", monospace';
    const sw = ctx.measureText(status).width;
    const bw = Math.max(tw, sw) + 24;
    const bh = 40;
    let bx = hv.x + 16;
    let by = hv.y - bh - 10;
    // flip the chip when it would run off the right/top edge
    if (bx + bw > w - 12) bx = hv.x - bw - 16;
    if (by < 12) by = hv.y + 16;
    ctx.fillStyle = 'rgba(6,23,16,0.92)';
    ctx.strokeStyle = 'rgba(143,217,168,0.4)';
    ctx.beginPath();
    ctx.roundRect(bx, by, bw, bh, 9);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = '#F6F8F4';
    ctx.font = '600 12px "DM Sans", sans-serif';
    ctx.fillText(label, bx + 12, by + 17);
    ctx.fillStyle = cp < 0.05 ? '#9a9a9a' : hv.n.final;
    ctx.font = '9px "JetBrains Mono", monospace';
    ctx.fillText(status, bx + 12, by + 31);
  }
}

/** ── explore view ───────────────────────────────────────────────────── */
export function drawExplore(
  canvas: HTMLCanvasElement,
  graph: BuiltGraph,
  st: GraphViewState,
  selected: number | null,
): void {
  const c = cv(canvas);
  const { ctx, w, h } = c;
  ctx.clearRect(0, 0, w, h);

  const { nodes, edges, adj } = graph;
  const t = Date.now() * 0.001;
  let k = clamp01((performance.now() - (st.expT0 || 0)) / 850);
  if (st.expOut) k = 1 - k;
  const e = smooth(k);

  // the whole graph, a step closer: no new layout, just a tighter camera
  const fit = Math.min(1.4, Math.max(0.66, w / 1180));
  const zoomTo = fit * 1.42 * (st.expZoom || 1);
  const from = st.camFrom || {
    zoom: zoomTo, cx: w * 0.5, cy: h * 0.48, rotY: st.orbY, rotX: st.orbX,
  };
  const zoom = from.zoom + (zoomTo - from.zoom) * e;
  // drift left to make room for the detail panel
  const cx = from.cx + (w * 0.42 - from.cx) * e;
  const cy = from.cy + (h * 0.5 - from.cy) * e;
  const rotY = st.orbY + t * 0.035;
  const rotX = st.orbX;

  const cosY = Math.cos(rotY), sinY = Math.sin(rotY);
  const cosX = Math.cos(rotX), sinX = Math.sin(rotX);
  const proj: Projected[] = nodes.map((n, i) => {
    const wob = Math.sin(t * 0.5 + n.seed) * 8;
    const x = n.ox * cosY - n.oz * sinY;
    const z = n.oz * cosY + n.ox * sinY;
    const y = (n.oy + wob) * cosX - z * sinX * 0.4;
    const sc = (FL / (FL + z)) * zoom;
    return { x: x * sc + cx, y: y * sc + cy, z, sc, n, i };
  });

  let ck = clamp01((performance.now() - (st.expT0 || 0)) / 1250);
  if (st.expOut) ck = 1 - ck;

  const sel = selected;
  const hasSel = sel !== null && sel !== undefined;
  const near: Record<number, 1> = {};
  if (hasSel) {
    near[sel] = 1;
    (adj[sel] || []).forEach((j) => { near[j] = 1; });
  }

  // continue each node's spawn from where the scroll view left it
  const spOf = (i: number) => {
    const sf = st.expSpFrom ? (st.expSpFrom[i] === undefined ? 1 : st.expSpFrom[i]) : 1;
    const stag = st.expOrder ? st.expOrder[i] || 0 : 0;
    const own = smooth(clamp01((ck - stag * 0.4) / (1 - stag * 0.4 || 1)));
    return sf + (1 - sf) * own;
  };

  edges.forEach((ed) => {
    const a = proj[ed.a], b = proj[ed.b];
    const hot = hasSel && (ed.a === sel || ed.b === sel);
    const dim = hasSel && !hot ? 0.3 : 1;
    const eReveal = Math.min(spOf(ed.a), spOf(ed.b));
    if (eReveal <= 0.01) return;
    ctx.globalAlpha = dim * eReveal;
    ctx.strokeStyle = hot
      ? 'rgba(143,217,168,0.55)'
      : 'rgba(143,217,168,' + (ed.cross ? 0.1 : 0.16) + ')';
    ctx.lineWidth = hot ? 1.6 : 0.7;
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.stroke();
  });
  ctx.globalAlpha = 1;

  st.expProj = proj;
  const hover = st.expHover;
  // labels and mastery arcs fade in over the back half of the entry
  const la = smooth(clamp01((e - 0.45) / 0.55));

  proj
    .slice()
    .sort((a, b) => b.z - a.z)
    .forEach((pr) => {
      const n = pr.n;
      const dim = hasSel && !near[pr.i] ? 0.28 : 1;
      const breathe = 0.94 + 0.06 * Math.sin(t * 0.7 + n.seed);
      const fog = pr.z > 400 ? Math.max(0.25, 1 - (pr.z - 400) / 800) : 1;
      let r = n.r * pr.sc * breathe * (hover === pr.i ? 1.35 : 1);
      if (r < 0.2) return;

      const stag = st.expOrder ? st.expOrder[pr.i] || 0 : 0;
      const own = smooth(clamp01((ck - stag * 0.4) / (1 - stag * 0.4 || 1)));
      const cf = st.expCpFrom ? st.expCpFrom[pr.i] || 0 : 1;
      const cp = cf + (1 - cf) * own;
      const col = cp >= 0.999 ? n.final : lerpColor(GREY, n.final, cp);

      // a node still mid-spawn keeps growing in rather than appearing at full size
      const sf = st.expSpFrom ? (st.expSpFrom[pr.i] === undefined ? 1 : st.expSpFrom[pr.i]) : 1;
      const sp = sf + (1 - sf) * own;
      if (sp <= 0.001) return;
      const grow = sp < 1 ? (1.4 - 0.4 * sp) * sp : 1;
      r *= grow;

      ctx.globalAlpha = dim * fog * Math.min(1, sp * 1.6);
      ctx.beginPath();
      ctx.arc(pr.x, pr.y, r, 0, Math.PI * 2);
      ctx.fillStyle = col;
      ctx.fill();

      // mastery arc: the ring the app draws around every concept
      const ar = r + (n.root ? 9 : 6) * pr.sc;
      ctx.globalAlpha = dim * fog * la;
      ctx.beginPath();
      ctx.arc(pr.x, pr.y, ar, 0, Math.PI * 2);
      ctx.strokeStyle = 'rgba(230,242,232,0.13)';
      ctx.lineWidth = 2.2 * pr.sc;
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(pr.x, pr.y, ar, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * n.mastery);
      ctx.strokeStyle = col;
      ctx.lineWidth = 2.2 * pr.sc;
      ctx.stroke();

      if (pr.i === sel) {
        ctx.globalAlpha = 1;
        ctx.beginPath();
        ctx.arc(pr.x, pr.y, ar + 8 * pr.sc, 0, Math.PI * 2);
        ctx.strokeStyle = 'rgba(230,242,232,0.5)';
        ctx.lineWidth = 1.4;
        ctx.stroke();
      }

      // labels: units always, concepts once they are close enough to read
      const show = n.hub || pr.sc > 0.62 || pr.i === sel || near[pr.i] || hover === pr.i;
      if (show) {
        ctx.globalAlpha = dim * la * (n.hub ? 0.95 : 0.72);
        ctx.font = n.root
          ? '600 14px "JetBrains Mono", monospace'
          : n.hub
            ? '11px "JetBrains Mono", monospace'
            : '11px "DM Sans", sans-serif';
        ctx.fillStyle = n.root ? '#F6F8F4' : n.hub ? '#B9D9C4' : '#8FA89A';
        ctx.textAlign = 'center';
        ctx.fillText(n.hub ? n.label.toUpperCase() : n.label, pr.x, pr.y + ar + 15 * pr.sc + 4);
        ctx.textAlign = 'left';
      }
      ctx.globalAlpha = 1;
    });
}
