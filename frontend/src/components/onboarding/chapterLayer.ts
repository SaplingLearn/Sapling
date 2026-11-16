/**
 * The onboarding layer of a node-graph canvas: the camera zoom (rest 1x,
 * intro 2.5x, outro 5.5x), the link fade as clusters form, and the chapter
 * clusters (a faint preview for the active chapter, 15 nodes migrating in per
 * finished one). From the Claude Design onboarding handoff.
 *
 * Renderer-agnostic: OnboardingGraph draws its ambient scene and hands this
 * layer the camera and the chapter state. (It also drove the landing hero's
 * canvas while Get Started played onboarding over the landing; that takeover
 * went with sign-in-first onboarding.)
 */

export type GraphPhase = "idle" | "out" | "active" | "complete";
export type GraphZoom = "rest" | "active" | "outro";

export interface ChapterState {
  phase: GraphPhase;
  zoom: GraphZoom;
  activeChapter: number;
  completed: number[];
}

const CENTERS = [
  { ox: -230, oy: -80, oz: 25 }, { ox: -115, oy: -105, oz: -35 }, { ox: -270, oy: 65, oz: -15 },
  { ox: -155, oy: 95, oz: 35 }, { ox: -215, oy: -25, oz: -55 },
  { ox: -250, oy: -165, oz: -20 }, { ox: -215, oy: 165, oz: 30 },
];
// Chapter clusters in main's olive landing palette (amber first, as the
// pre-#292 OB_STEP_COLORS had it), so they match the hero nodes around them.
const STEP = ["#D97706", "#445D22", "#7B9E51", "#B1D28B", "#E27A63", "#A39E8F"];
const ZOOM_TARGET: Record<GraphZoom, number> = { rest: 1, active: 2.5, outro: 5.5 };
const FL = 1000;
/** Opacity the scene's own (ambient) nodes and links settle at once onboarding starts. */
const AMBIENT_DIM = 0.3;

interface ChapterNode {
  ox: number; oy: number; oz: number; startOx: number; startOy: number; startOz: number;
  migDelay: number; migDur: number; stepIndex: number; radius: number; seed: number;
  birthTime: number; isPreview: boolean; dyingAt?: number;
}

/** Deterministic per-(chapter, index) noise so clusters land the same way every time. */
const rnd = (si: number, idx: number) => {
  const s = Math.sin(si * 9301 + idx * 49297 + 233) * 10000003;
  return s - Math.floor(s);
};
const ease = (x: number) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);

export interface ChapterLayer {
  /**
   * Advance one frame. Returns the camera zoom, how far clusters have formed
   * (0..1), and the opacity for the scene's ambient nodes (1 at rest, dimmed
   * during onboarding so the chapter clusters and the UI read over them).
   */
  step(nowMs: number, dtF: number, s: ChapterState): { zoom: number; clusterProgress: number; ambientAlpha: number };
  /** Draw the chapter clusters with the scene's rotation and centre. */
  draw(ctx: CanvasRenderingContext2D, nowMs: number, t: number, rot: number, cx: number, cy: number): void;
}

export function createChapterLayer(): ChapterLayer {
  let nodes: ChapterNode[] = [];
  let initSteps = new Set<number>();
  let doneSteps = new Set<number>();
  let zoom = 1;
  let clusterProgress = 0;
  let ambientAlpha = 1;

  return {
    step(nowMs, dtF, s) {
      if (s.phase === "idle") {
        // Not started (or reset): drop the clusters so a replay starts clean.
        nodes = []; initSteps = new Set(); doneSteps = new Set();
      }
      if (s.phase === "active" && !initSteps.has(s.activeChapter)) {
        const asi = s.activeChapter;
        initSteps.add(asi);
        const c = CENTERS[asi];
        for (let k = 0; k < 8; k++) {
          const ox = c.ox + (rnd(asi, k * 4) - 0.5) * 58 * 0.9;
          const oy = c.oy + (rnd(asi, k * 4 + 1) - 0.5) * 58 * 0.6;
          const oz = c.oz + (rnd(asi, k * 4 + 2) - 0.5) * 58 * 0.9;
          nodes.push({
            ox, oy, oz, startOx: ox, startOy: oy, startOz: oz, migDelay: k * 60, migDur: 450, stepIndex: asi,
            radius: 1 + rnd(asi, k * 4 + 3) * 1.5, seed: rnd(asi, k * 4 + 2) * 100, birthTime: nowMs, isPreview: true,
          });
        }
      }
      if (s.phase === "active" || s.phase === "complete") {
        for (const si of s.completed) {
          if (doneSteps.has(si)) continue;
          doneSteps.add(si);
          nodes.forEach(n => { if (n.stepIndex === si && n.isPreview) n.dyingAt = nowMs; });
          const c = CENTERS[si];
          for (let k = 0; k < 15; k++) {
            nodes.push({
              ox: c.ox + (rnd(si, k * 4) - 0.5) * 116, oy: c.oy + (rnd(si, k * 4 + 1) - 0.5) * 87, oz: c.oz + (rnd(si, k * 4 + 2) - 0.5) * 116,
              startOx: 80 + rnd(si, k * 4 + 10) * 260, startOy: (rnd(si, k * 4 + 11) - 0.5) * 220, startOz: (rnd(si, k * 4 + 12) - 0.5) * 220,
              migDelay: k * 50, migDur: 580 + rnd(si, k * 4 + 13) * 160, stepIndex: si,
              radius: 1.8 + rnd(si, k * 4 + 3) * 3, seed: rnd(si, k * 4 + 2) * 100, birthTime: nowMs, isPreview: false,
            });
          }
        }
      }
      nodes = nodes.filter(n => !(n.dyingAt !== undefined && nowMs - n.dyingAt > 500));
      zoom += (ZOOM_TARGET[s.zoom] - zoom) * (1 - Math.pow(0.975, dtF));
      clusterProgress = s.zoom !== "rest"
        ? Math.min(1, clusterProgress + 0.01 * dtF)
        : Math.max(0, clusterProgress - 0.015 * dtF);
      const dimTarget = s.phase === "idle" ? 1 : AMBIENT_DIM;
      ambientAlpha += (dimTarget - ambientAlpha) * (1 - Math.pow(0.96, dtF));
      return { zoom, clusterProgress, ambientAlpha };
    },

    draw(ctx, nowMs, t, rot, cx, cy) {
      if (nodes.length === 0) return;
      const proj = nodes.flatMap(n => {
        const elapsed = nowMs - n.birthTime;
        const rawMigP = (elapsed - n.migDelay) / n.migDur;
        if (rawMigP < 0) return [];
        const migP = Math.min(1, rawMigP), em = ease(migP);
        const ox = n.startOx + (n.ox - n.startOx) * em, oy = n.startOy + (n.oy - n.startOy) * em, oz = n.startOz + (n.oz - n.startOz) * em;
        const arrP = Math.min(1, Math.max(0, (elapsed - n.migDelay - n.migDur) / 400));
        const popScale = migP < 1 ? 0.4 + 0.6 * migP : 1.0 + Math.sin(arrP * Math.PI) * 0.12;
        const dying = n.dyingAt !== undefined ? 1.0 - ease(Math.min(1, (nowMs - n.dyingAt) / 350)) : 1.0;
        const alpha = (migP < 1 ? em : 1.0) * dying;
        if (alpha < 0.005) return [];
        const ny = oy + Math.sin(t * 0.4 + n.seed) * 8 * migP;
        const rx = ox * Math.cos(rot) - oz * Math.sin(rot);
        const rz = oz * Math.cos(rot) + ox * Math.sin(rot);
        const sc = FL / (FL + rz);
        return [{ x: rx * sc * zoom + cx, y: ny * sc * zoom + cy, z: rz, sc, n, alpha, popScale, migP, arrP, color: STEP[n.stepIndex] }];
      }).sort((a, b) => b.z - a.z);

      ctx.lineWidth = 0.7;
      for (let i = 0; i < proj.length; i++) {
        const p1 = proj[i];
        if (p1.migP < 1 || p1.alpha < 0.1) continue;
        const maxD = 90 * p1.sc * zoom, maxD2 = maxD * maxD;
        const cr = parseInt(p1.color.slice(1, 3), 16), cg = parseInt(p1.color.slice(3, 5), 16), cb = parseInt(p1.color.slice(5, 7), 16);
        for (let j = i + 1; j < proj.length; j++) {
          const p2 = proj[j];
          if (p2.migP < 1 || p2.alpha < 0.1) continue;
          const dx = p1.x - p2.x; if (dx > maxD || dx < -maxD) continue;
          const dy = p1.y - p2.y; if (dy > maxD || dy < -maxD) continue;
          const d2 = dx * dx + dy * dy; if (d2 >= maxD2) continue;
          const a = (1 - Math.sqrt(d2) / maxD) * 0.35 * Math.min(p1.arrP, p2.arrP) * Math.min(p1.alpha, p2.alpha);
          if (a > 0.003) {
            ctx.strokeStyle = p1.n.isPreview && p2.n.isPreview
              ? `rgba(200,210,200,${(a * 0.35).toFixed(4)})`
              : `rgba(${cr},${cg},${cb},${a.toFixed(4)})`;
            ctx.beginPath(); ctx.moveTo(p1.x, p1.y); ctx.lineTo(p2.x, p2.y); ctx.stroke();
          }
        }
      }
      for (const p of proj) {
        const breathe = 0.92 + 0.08 * Math.sin(t * 0.6 + p.n.seed);
        const r = Math.max(0.1, p.n.radius * p.sc * zoom * breathe * p.popScale);
        if (p.n.isPreview) { ctx.globalAlpha = (0.25 + 0.2 * Math.sin(t * 3 + p.n.seed)) * p.alpha; ctx.shadowBlur = 10; }
        else { ctx.globalAlpha = p.alpha; ctx.shadowBlur = p.migP >= 1 ? 18 * (0.7 + 0.3 * Math.sin(t * 1.5 + p.n.seed * 0.3)) : 6; }
        ctx.shadowColor = p.color; ctx.fillStyle = p.color;
        ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, Math.PI * 2); ctx.fill();
      }
      ctx.shadowBlur = 0; ctx.shadowColor = "transparent"; ctx.globalAlpha = 1;
    },
  };
}
