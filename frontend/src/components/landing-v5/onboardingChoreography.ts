/**
 * The onboarding choreography's canvas half.
 *
 * Signup runs in place on the landing page: the hero dims, the hero's
 * point-cloud canvas dives 1.0 → 2.5 into a knowledge graph, and
 * `OnboardingFlow` rides on top of it. Each step the visitor completes flies
 * its own colour cluster in from off-screen right; the outro dives to 5.5
 * under "Welcome to Sapling" before handing off to /dashboard.
 *
 * This module owns everything the canvas needs and nothing the form does. The
 * page (`(public)/page.tsx`) owns the phase machine and writes it into the ref
 * bundle below; `Hero`'s RAF reads the bundle and calls the two functions
 * here. The split is deliberate — the RAF closes over its setup exactly once
 * and must not re-run (and re-seed all 226 ambient nodes) on a state change,
 * so every value it needs crosses the boundary as a ref, never a prop.
 *
 * Originally inline in main's landing page (restored there by cd687e7d); the
 * v5 landing split that page into components, so the phase machine and the
 * canvas work had to be separated to follow.
 */

import { useState } from 'react';

export type ObPhase = 'idle' | 'out' | 'active' | 'complete';

/**
 * One per onboarding step, in step order — the colour that step's cluster
 * grows in. `#3e6f8a` rather than a neon `#3B82F6` for the #106 de-neon
 * reason; `OnboardingFlow`'s STEPS array mirrors this list.
 */
export const OB_STEP_COLORS = ['#D97706', '#8A63D2', '#3e6f8a', '#14B8A6', '#EF4444'];

/**
 * Cluster centre per step, in the left-hand third the form doesn't cover.
 * Nodes migrate in from off-screen right as steps complete.
 */
const OB_STEP_CENTERS = [
  { ox: -230, oy: -80, oz:  25 },
  { ox: -115, oy:-105, oz: -35 },
  { ox: -270, oy:  65, oz: -15 },
  { ox: -155, oy:  95, oz:  35 },
  { ox: -215, oy: -25, oz: -55 },
];
const OB_SPREAD = 58;
const OB_COUNT = 15;

const easeInOutCubic = (x: number) =>
  x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;

/**
 * Deterministic per-(step, index) jitter — a hash, not a PRNG, so a node's
 * position is identical on every replay of the same step. Independent of
 * testMode's `random()` seam for that reason.
 */
const stepRand = (si: number, idx: number) => {
  const s = Math.sin(si * 9301 + idx * 49297 + 233) * 10000003;
  return s - Math.floor(s);
};

interface ObNode {
  ox: number; oy: number; oz: number;
  startOx: number; startOy: number; startOz: number;
  migDelay: number; migDur: number;
  color: string; radius: number; seed: number;
  birthTime: number; stepIndex: number; isPreview: boolean;
  dyingAt?: number;
}

/** Everything that crosses from the page's phase machine into Hero's RAF. */
export interface ObRefs {
  /** The phase machine's current state, mirrored for the RAF. */
  phase: React.MutableRefObject<ObPhase>;
  /** Current lerped canvas zoom. Lives across frames. */
  zoom: React.MutableRefObject<number>;
  /** True once the intro text has played: zoom targets 2.5. */
  zoomActive: React.MutableRefObject<boolean>;
  /** True on the outro dive: zoom targets 5.5 instead. */
  zoomOutro: React.MutableRefObject<boolean>;
  /** 0 → 1 as the ambient field fades back so the OB graph reads. */
  clusterProgress: React.MutableRefObject<number>;
  /** Step the form is currently on — spawns that step's preview nodes. */
  activeStep: React.MutableRefObject<number>;
  /** Steps the visitor has finished — each flies its real cluster in. */
  completed: React.MutableRefObject<Set<number>>;
  nodes: React.MutableRefObject<ObNode[]>;
  initSteps: React.MutableRefObject<Set<number>>;
  doneSteps: React.MutableRefObject<Set<number>>;
  /**
   * Written by Hero's canvas effect: whether the RAF is actually live. Under
   * reduced motion / test mode it is parked on one deterministic frame, so
   * there is no zoom to watch and the page skips the choreography entirely.
   */
  canvasAnimating: React.MutableRefObject<boolean>;
}

/**
 * The bundle, built once per mount.
 *
 * `useState` with a lazy initialiser rather than `useRef`, for two reasons:
 * the identity is stable, so effects (and the hero's canvas effect) can list
 * the bundle as a dependency and mean it; and nothing reads a `.current`
 * during render, which `react-hooks/refs` forbids. The cells are plain
 * objects — a ref is only ever `{ current }` — so the RAF mutates them
 * without React ever re-rendering.
 */
export function useObRefs(): ObRefs {
  const [bundle] = useState<ObRefs>(() => ({
    phase: { current: 'idle' },
    zoom: { current: 1.0 },
    zoomActive: { current: false },
    zoomOutro: { current: false },
    clusterProgress: { current: 0 },
    activeStep: { current: 0 },
    completed: { current: new Set() },
    nodes: { current: [] },
    initSteps: { current: new Set() },
    doneSteps: { current: new Set() },
    canvasAnimating: { current: true },
  }));
  return bundle;
}

/*
 * Every write to the bundle goes through one of the functions below rather
 * than through a member assignment at the call site. `useObRefs` returns it
 * from a hook, and `react-hooks/immutability` (rightly) refuses mutation of a
 * hook's return value in the component — the state machine should be asking
 * for a transition, not reaching into the canvas's fields.
 */

/** Mirrors the page's phase machine into the frame loop. */
export function syncObState(
  ob: ObRefs,
  next: { phase?: ObPhase; activeStep?: number; completed?: Set<number> },
) {
  if (next.phase !== undefined) ob.phase.current = next.phase;
  if (next.activeStep !== undefined) ob.activeStep.current = next.activeStep;
  if (next.completed !== undefined) ob.completed.current = next.completed;
}

/** Resets the canvas half to its un-zoomed, un-clustered state. */
export function resetObGraph(ob: ObRefs) {
  ob.zoom.current = 1.0;
  ob.clusterProgress.current = 0;
  ob.zoomActive.current = false;
  ob.zoomOutro.current = false;
}

/** The intro has played: dive 1.0 → 2.5 and start forming the clusters. */
export function armObZoom(ob: ObRefs) {
  ob.zoomActive.current = true;
  ob.zoomOutro.current = false;
}

/** The outro: dive on to 5.5 under "Welcome to Sapling". */
export function armObOutro(ob: ObRefs) {
  ob.zoomOutro.current = true;
}

/**
 * Closing the flow: drop both zoom targets so the dive *eases* back to 1.0 and
 * the ambient field fades back in. Deliberately not `resetObGraph` — that
 * snaps, which is right for arming the intro and wrong for leaving.
 */
export function releaseObZoom(ob: ObRefs) {
  ob.zoomActive.current = false;
  ob.zoomOutro.current = false;
}

/** Marks every live node as dying, so closing the flow fades them out. */
export function retireObNodes(ob: ObRefs, nowMs: number) {
  ob.nodes.current.forEach(n => { if (n.dyingAt === undefined) n.dyingAt = nowMs; });
}

/** Called by the hero's canvas effect; see `ObRefs.canvasAnimating`. */
export function setObCanvasAnimating(ob: ObRefs, animating: boolean) {
  ob.canvasAnimating.current = animating;
}

/** Whether there is a zoom to watch, or the flow should open the form flat. */
export function obCanvasAnimating(ob: ObRefs) {
  return ob.canvasAnimating.current;
}

/**
 * The frame's first half: spawn and retire nodes, then advance the zoom and
 * cluster lerps. Returns the values the ambient field needs — it shares the
 * zoom, and dims as `clusterProgress` rises.
 *
 * Called before the ambient projection because that projection needs `zoom`.
 */
export function stepObGraph(ob: ObRefs | null, nowMs: number) {
  if (!ob) return { zoom: 1, clusterProgress: 0, linkFade: 1 };

  const phase = ob.phase.current;

  // This step's preview nodes: eight faint ones, hinting at the cluster the
  // step will grow into once it's answered.
  if (phase === 'active') {
    const asi = ob.activeStep.current;
    if (!ob.initSteps.current.has(asi)) {
      ob.initSteps.current.add(asi);
      const ctr = OB_STEP_CENTERS[asi];
      for (let k = 0; k < 8; k++) {
        const ox = ctr.ox + (stepRand(asi, k * 4    ) - 0.5) * OB_SPREAD * 0.9;
        const oy = ctr.oy + (stepRand(asi, k * 4 + 1) - 0.5) * OB_SPREAD * 0.6;
        const oz = ctr.oz + (stepRand(asi, k * 4 + 2) - 0.5) * OB_SPREAD * 0.9;
        ob.nodes.current.push({
          ox, oy, oz, startOx: ox, startOy: oy, startOz: oz,
          migDelay: k * 60, migDur: 450,
          color: OB_STEP_COLORS[asi],
          radius: 1 + stepRand(asi, k * 4 + 3) * 1.5,
          seed: stepRand(asi, k * 4 + 2) * 100,
          birthTime: nowMs, stepIndex: asi, isPreview: true,
        });
      }
    }
  }

  // A completed step's preview dies and its real cluster flies in.
  if (phase === 'active' || phase === 'complete') {
    ob.completed.current.forEach(si => {
      if (ob.doneSteps.current.has(si)) return;
      ob.doneSteps.current.add(si);
      ob.nodes.current.forEach(n => {
        if (n.stepIndex === si && n.isPreview) n.dyingAt = nowMs;
      });
      const ctr = OB_STEP_CENTERS[si];
      for (let k = 0; k < OB_COUNT; k++) {
        ob.nodes.current.push({
          ox: ctr.ox + (stepRand(si, k * 4    ) - 0.5) * OB_SPREAD * 2,
          oy: ctr.oy + (stepRand(si, k * 4 + 1) - 0.5) * OB_SPREAD * 1.5,
          oz: ctr.oz + (stepRand(si, k * 4 + 2) - 0.5) * OB_SPREAD * 2,
          startOx: 80 + stepRand(si, k * 4 + 10) * 260,
          startOy: (stepRand(si, k * 4 + 11) - 0.5) * 220,
          startOz: (stepRand(si, k * 4 + 12) - 0.5) * 220,
          migDelay: k * 50, migDur: 580 + stepRand(si, k * 4 + 13) * 160,
          color: OB_STEP_COLORS[si],
          radius: 1.8 + stepRand(si, k * 4 + 3) * 3,
          seed: stepRand(si, k * 4 + 2) * 100,
          birthTime: nowMs, stepIndex: si, isPreview: false,
        });
      }
    });
  }

  if (ob.nodes.current.length > 0) {
    ob.nodes.current = ob.nodes.current.filter(n =>
      !(n.dyingAt !== undefined && nowMs - n.dyingAt > 500)
    );
    if (phase === 'idle') {
      ob.nodes.current = [];
      ob.initSteps.current = new Set();
      ob.doneSteps.current = new Set();
    }
  }

  // Zoom 1.0 → 2.5 on entering the form, → 5.5 on the outro dive.
  const zoomTarget = ob.zoomOutro.current ? 5.5 : (ob.zoomActive.current ? 2.5 : 1.0);
  ob.zoom.current += (zoomTarget - ob.zoom.current) * 0.025;

  ob.clusterProgress.current = ob.zoomActive.current
    ? Math.min(1, ob.clusterProgress.current + 0.01)
    : Math.max(0, ob.clusterProgress.current - 0.015);

  const clusterProgress = ob.clusterProgress.current;
  return {
    zoom: ob.zoom.current,
    clusterProgress,
    linkFade: Math.max(0, 1 - clusterProgress),
  };
}

/**
 * The frame's second half: migrate, link and draw the per-step clusters over
 * the (by now dimmed) ambient field. A no-op until there are nodes, which is
 * every frame outside the flow.
 */
export function drawObGraph(
  ctx: CanvasRenderingContext2D,
  ob: ObRefs | null,
  view: {
    nowMs: number; t: number; rotAngle: number;
    fl: number; cx: number; cy: number; zoom: number; parallaxY: number;
  },
) {
  if (!ob || ob.nodes.current.length === 0) return;
  const { nowMs, t, rotAngle, fl, cx, cy, zoom, parallaxY } = view;

  const obProj = ob.nodes.current.flatMap(n => {
    const elapsed = nowMs - n.birthTime;
    const rawMigP = (elapsed - n.migDelay) / n.migDur;
    if (rawMigP < 0) return [];
    const migP = Math.min(1, rawMigP);
    const easedM = easeInOutCubic(migP);
    const curOx = n.startOx + (n.ox - n.startOx) * easedM;
    const curOy = n.startOy + (n.oy - n.startOy) * easedM;
    const curOz = n.startOz + (n.oz - n.startOz) * easedM;
    const arrP = Math.min(1, Math.max(0, (elapsed - n.migDelay - n.migDur) / 400));
    const popScale = migP < 1 ? 0.4 + 0.6 * migP : 1.0 + Math.sin(arrP * Math.PI) * 0.12;
    const baseAlpha = migP < 1 ? easedM : 1.0;
    const dyingFade = n.dyingAt !== undefined
      ? 1.0 - easeInOutCubic(Math.min(1, (nowMs - n.dyingAt) / 350))
      : 1.0;
    const alpha = baseAlpha * dyingFade;
    if (alpha < 0.005) return [];
    const ny = curOy + Math.sin(t * 0.4 + n.seed) * 8 * migP;
    const rx = curOx * Math.cos(rotAngle) - curOz * Math.sin(rotAngle);
    const rz = curOz * Math.cos(rotAngle) + curOx * Math.sin(rotAngle);
    const sc = fl / (fl + rz);
    return [{
      x: rx * sc * zoom + cx,
      y: ny * sc * zoom + cy - parallaxY,
      z: rz, sc, n, alpha, popScale, migP, arrP,
    }];
  }).sort((a, b) => b.z - a.z);

  // Same shape as the ambient pair walk: hoisted threshold, |dx|/|dy| reject
  // before the multiply, squared-distance compare so the sqrt only runs for
  // pairs that actually draw a link.
  ctx.lineWidth = 0.7;
  for (let i = 0; i < obProj.length; i++) {
    const p1 = obProj[i];
    if (p1.migP < 1 || p1.alpha < 0.1) continue;
    const maxD = 90 * p1.sc * zoom;
    const maxD2 = maxD * maxD;
    const col = p1.n.color;
    const cr = parseInt(col.slice(1, 3), 16);
    const cg = parseInt(col.slice(3, 5), 16);
    const cb = parseInt(col.slice(5, 7), 16);
    for (let j = i + 1; j < obProj.length; j++) {
      const p2 = obProj[j];
      if (p2.migP < 1 || p2.alpha < 0.1) continue;
      const dx = p1.x - p2.x;
      if (dx > maxD || dx < -maxD) continue;
      const dy = p1.y - p2.y;
      if (dy > maxD || dy < -maxD) continue;
      const d2 = dx * dx + dy * dy;
      if (d2 >= maxD2) continue;
      const a = (1 - Math.sqrt(d2) / maxD) * 0.35
        * Math.min(p1.arrP, p2.arrP) * Math.min(p1.alpha, p2.alpha);
      if (a > 0.003) {
        ctx.strokeStyle = (p1.n.isPreview && p2.n.isPreview)
          ? `rgba(200,210,200,${(a * 0.35).toFixed(4)})`
          : `rgba(${cr},${cg},${cb},${a.toFixed(4)})`;
        ctx.beginPath(); ctx.moveTo(p1.x, p1.y); ctx.lineTo(p2.x, p2.y); ctx.stroke();
      }
    }
  }

  obProj.forEach(p => {
    const breathe = 0.92 + 0.08 * Math.sin(t * 0.6 + p.n.seed);
    const r = Math.max(0.1, p.n.radius * p.sc * zoom * breathe * p.popScale);
    if (p.n.isPreview) {
      ctx.globalAlpha = (0.25 + 0.2 * Math.sin(t * 3 + p.n.seed)) * p.alpha;
      ctx.shadowBlur = 10;
    } else {
      ctx.globalAlpha = p.alpha;
      ctx.shadowBlur = p.migP >= 1 ? 18 * (0.7 + 0.3 * Math.sin(t * 1.5 + p.n.seed * 0.3)) : 6;
    }
    ctx.shadowColor = p.n.color;
    ctx.fillStyle = p.n.color;
    ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, Math.PI * 2); ctx.fill();
  });
  ctx.shadowBlur = 0;
  ctx.shadowColor = 'transparent';
  ctx.globalAlpha = 1;
}
