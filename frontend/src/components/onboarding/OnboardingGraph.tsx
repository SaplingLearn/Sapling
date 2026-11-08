"use client";

/**
 * The 3D node field behind every onboarding screen (Claude Design handoff,
 * "Background graph"). Ambient nodes drift and rotate; each completed chapter
 * migrates a 15-node cluster into place, and the active chapter shows a faint
 * preview cluster. The zoom drives the intro (2.5) and the outro (5.5).
 *
 * The renderer runs off refs, not React state: props are copied into a
 * mutable `live` object every render and the rAF loop reads from it.
 */
import { useEffect, useRef } from "react";

export type GraphPhase = "idle" | "out" | "active" | "complete";
export type GraphZoom = "rest" | "active" | "outro";

interface Props {
  phase: GraphPhase;
  zoom: GraphZoom;
  activeChapter: number;
  completed: number[];
  /** Rotation speed multiplier (design default 0.5). */
  speed?: number;
}

const CENTERS = [
  { ox: -230, oy: -80, oz: 25 }, { ox: -115, oy: -105, oz: -35 }, { ox: -270, oy: 65, oz: -15 },
  { ox: -155, oy: 95, oz: 35 }, { ox: -215, oy: -25, oz: -55 },
  { ox: -250, oy: -165, oz: -20 }, { ox: -215, oy: 165, oz: 30 },
];
const STEP = ["#D97706", "#8A63D2", "#14B8A6", "#3e6f8a", "#EF4444", "#7C9A2E", "#4a7d5c"];
const AMB = ["#8A63D2", "#3e6f8a", "#D97706", "#14B8A6", "#9CA3AF", "#D1D5DB"];
const HERO = ["#9CA3AF", "#D97706", "#3e6f8a", "#8A63D2", "#14B8A6", "#EF4444"];
const AMB_WEIGHTS = [0.24, 0.24, 0.2, 0.15, 0.1, 0.07];
const AMBIENT_CLUSTERS = [
  { x: -600, y: -250, z: 80 }, { x: -350, y: -100, z: -120 }, { x: -100, y: -300, z: 200 }, { x: 150, y: -150, z: -80 },
  { x: 400, y: -250, z: 150 }, { x: 600, y: -100, z: -50 }, { x: -500, y: 100, z: -150 }, { x: -200, y: 200, z: 100 },
  { x: 50, y: 150, z: -200 }, { x: 300, y: 250, z: 120 }, { x: 550, y: 150, z: -100 }, { x: -400, y: 350, z: 60 },
  { x: 0, y: 0, z: 0 }, { x: 200, y: -50, z: -150 },
];
const HERO_INIT = [
  { ox: -222, oy: -29, oz: 15 }, { ox: -161, oy: -59, oz: -20 }, { ox: -81, oy: -42, oz: 30 },
  { ox: -67, oy: 17, oz: 0 }, { ox: -168, oy: 59, oz: 20 }, { ox: -229, oy: 8, oz: -30 },
];
const HERO_SEEDS = [10.0, 11.3, 12.6, 13.9, 15.2, 16.5];
const ZOOM_TARGET: Record<GraphZoom, number> = { rest: 1, active: 2.5, outro: 5.5 };
const FL = 1000;

interface AmbientNode { ox: number; oy: number; oz: number; pi: number; hc: number; radius: number; seed: number }
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

function makeAmbient(): AmbientNode[] {
  const R = Math.random;
  const pick = () => {
    const r = R();
    let s = 0;
    for (let i = 0; i < AMB_WEIGHTS.length; i++) { s += AMB_WEIGHTS[i]; if (r <= s) return i; }
    return 0;
  };
  const bg = Array.from({ length: 220 }, () => {
    const cl = AMBIENT_CLUSTERS[Math.floor(R() * AMBIENT_CLUSTERS.length)];
    return {
      ox: cl.x + (R() - 0.5) * 280, oy: cl.y + (R() - 0.5) * 280, oz: cl.z + (R() - 0.5) * 280,
      pi: pick(), hc: -1, radius: 1 + R() * 4, seed: R() * 100,
    };
  });
  return bg.concat(HERO_INIT.map((p, i) => ({ ...p, pi: -1, hc: i, radius: 2.5 + R() * 1.5, seed: HERO_SEEDS[i] })));
}

export function OnboardingGraph({ phase, zoom, activeChapter, completed, speed = 0.5 }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const live = useRef({ phase, zoom, activeChapter, completed, speed });
  useEffect(() => { live.current = { phase, zoom, activeChapter, completed, speed }; });
  /** Set while the loop is paused (reduced motion), so prop changes still repaint. */
  const repaint = useRef<(() => void) | null>(null);
  useEffect(() => { repaint.current?.(); }, [phase, zoom, activeChapter, completed]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d", { alpha: true });
    if (!canvas || !ctx) return;

    const rm = window.matchMedia("(prefers-reduced-motion: reduce)");
    let animating = !rm.matches;
    const ambient = makeAmbient();
    let chapterNodes: ChapterNode[] = [];
    const initSteps = new Set<number>();
    const doneSteps = new Set<number>();
    let curZoom = 1;
    let clusterProgress = 0;
    let width = 0, height = 0, rot = 0, animId = 0, lastMs = 0;

    const step = (nowMs: number, dtF: number) => {
      const { phase: ph, activeChapter: asi, completed: done, zoom: z } = live.current;
      if (ph === "active" && !initSteps.has(asi)) {
        initSteps.add(asi);
        const c = CENTERS[asi];
        for (let k = 0; k < 8; k++) {
          const ox = c.ox + (rnd(asi, k * 4) - 0.5) * 58 * 0.9;
          const oy = c.oy + (rnd(asi, k * 4 + 1) - 0.5) * 58 * 0.6;
          const oz = c.oz + (rnd(asi, k * 4 + 2) - 0.5) * 58 * 0.9;
          chapterNodes.push({
            ox, oy, oz, startOx: ox, startOy: oy, startOz: oz, migDelay: k * 60, migDur: 450, stepIndex: asi,
            radius: 1 + rnd(asi, k * 4 + 3) * 1.5, seed: rnd(asi, k * 4 + 2) * 100, birthTime: nowMs, isPreview: true,
          });
        }
      }
      if (ph === "active" || ph === "complete") {
        for (const si of done) {
          if (doneSteps.has(si)) continue;
          doneSteps.add(si);
          chapterNodes.forEach(n => { if (n.stepIndex === si && n.isPreview) n.dyingAt = nowMs; });
          const c = CENTERS[si];
          for (let k = 0; k < 15; k++) {
            chapterNodes.push({
              ox: c.ox + (rnd(si, k * 4) - 0.5) * 116, oy: c.oy + (rnd(si, k * 4 + 1) - 0.5) * 87, oz: c.oz + (rnd(si, k * 4 + 2) - 0.5) * 116,
              startOx: 80 + rnd(si, k * 4 + 10) * 260, startOy: (rnd(si, k * 4 + 11) - 0.5) * 220, startOz: (rnd(si, k * 4 + 12) - 0.5) * 220,
              migDelay: k * 50, migDur: 580 + rnd(si, k * 4 + 13) * 160, stepIndex: si,
              radius: 1.8 + rnd(si, k * 4 + 3) * 3, seed: rnd(si, k * 4 + 2) * 100, birthTime: nowMs, isPreview: false,
            });
          }
        }
      }
      chapterNodes = chapterNodes.filter(n => !(n.dyingAt !== undefined && nowMs - n.dyingAt > 500));
      const zoomActive = z !== "rest";
      curZoom += (ZOOM_TARGET[z] - curZoom) * (1 - Math.pow(0.975, dtF));
      clusterProgress = zoomActive ? Math.min(1, clusterProgress + 0.01 * dtF) : Math.max(0, clusterProgress - 0.015 * dtF);
    };

    const drawChapters = (nowMs: number, t: number, cx: number, cy: number) => {
      if (chapterNodes.length === 0) return;
      const proj = chapterNodes.flatMap(n => {
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
        return [{ x: rx * sc * curZoom + cx, y: ny * sc * curZoom + cy, z: rz, sc, n, alpha, popScale, migP, arrP, color: STEP[n.stepIndex] }];
      }).sort((a, b) => b.z - a.z);

      ctx.lineWidth = 0.7;
      for (let i = 0; i < proj.length; i++) {
        const p1 = proj[i];
        if (p1.migP < 1 || p1.alpha < 0.1) continue;
        const maxD = 90 * p1.sc * curZoom, maxD2 = maxD * maxD;
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
        const r = Math.max(0.1, p.n.radius * p.sc * curZoom * breathe * p.popScale);
        if (p.n.isPreview) { ctx.globalAlpha = (0.25 + 0.2 * Math.sin(t * 3 + p.n.seed)) * p.alpha; ctx.shadowBlur = 10; }
        else { ctx.globalAlpha = p.alpha; ctx.shadowBlur = p.migP >= 1 ? 18 * (0.7 + 0.3 * Math.sin(t * 1.5 + p.n.seed * 0.3)) : 6; }
        ctx.shadowColor = p.color; ctx.fillStyle = p.color;
        ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, Math.PI * 2); ctx.fill();
      }
      ctx.shadowBlur = 0; ctx.shadowColor = "transparent"; ctx.globalAlpha = 1;
    };

    const draw = () => {
      ctx.clearRect(0, 0, width, height);
      const cx = width / 2, cy = height / 2, nowMs = performance.now(), t = nowMs * 0.001;
      const dtF = lastMs ? Math.min(4, (nowMs - lastMs) / 16.667) : 1;
      lastMs = nowMs;
      rot += 0.0008 * live.current.speed * dtF;
      step(nowMs, dtF);
      const linkFade = Math.max(0, 1 - clusterProgress);

      const proj = ambient.map(n => {
        const ny = n.oy + Math.sin(t * 0.4 + n.seed) * 15;
        const x = n.ox * Math.cos(rot) - n.oz * Math.sin(rot);
        const z = n.oz * Math.cos(rot) + n.ox * Math.sin(rot);
        const sc = FL / (FL + z);
        return { x: x * sc * curZoom + cx, y: ny * sc * curZoom + cy, z, sc: sc * curZoom, n };
      }).sort((a, b) => b.z - a.z);

      ctx.lineWidth = 0.5;
      for (let i = 0; linkFade > 0 && i < proj.length; i++) {
        const p1 = proj[i];
        const maxD = 70 * p1.sc, maxD2 = maxD * maxD;
        const aScale = 0.15 * Math.min(1, p1.sc) * linkFade;
        for (let j = i + 1; j < proj.length; j++) {
          const p2 = proj[j];
          const dx = p1.x - p2.x; if (dx > maxD || dx < -maxD) continue;
          const dy = p1.y - p2.y; if (dy > maxD || dy < -maxD) continue;
          const d2 = dx * dx + dy * dy;
          if (d2 < maxD2) {
            const a = (1 - Math.sqrt(d2) / maxD) * aScale;
            if (a > 0.002) { ctx.strokeStyle = `rgba(156,163,175,${a})`; ctx.beginPath(); ctx.moveTo(p1.x, p1.y); ctx.lineTo(p2.x, p2.y); ctx.stroke(); }
          }
        }
      }
      // Fog and cluster dimming only blend in with zoom progress, so the
      // pre-zoom field renders at full color (handoff "Fading rules").
      const zf = Math.max(0, Math.min(1, (curZoom - 1) / 1.5));
      for (const p of proj) {
        if (p.z <= -FL) continue;
        const breathe = 0.92 + 0.08 * Math.sin(t * 0.6 + p.n.seed);
        let fogA = p.z > 700 ? Math.max(0.6, 1 - (p.z - 700) / 900) : 1;
        if (clusterProgress > 0) fogA *= Math.max(0.75, 1 - clusterProgress * 0.25);
        fogA = 1 - (1 - fogA) * zf;
        const r = p.n.radius * p.sc * breathe;
        if (r > 0.1) {
          ctx.globalAlpha = fogA;
          ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
          ctx.fillStyle = p.n.hc >= 0 ? HERO[p.n.hc] : AMB[p.n.pi]; ctx.fill();
        }
      }
      ctx.globalAlpha = 1;
      drawChapters(nowMs, t, cx, cy);
      if (animating) animId = requestAnimationFrame(draw);
    };
    const syncRepaint = () => { repaint.current = animating ? null : draw; };

    const resize = () => {
      width = canvas.clientWidth || window.innerWidth;
      height = canvas.clientHeight || window.innerHeight;
      const d = window.devicePixelRatio || 1;
      canvas.width = width * d; canvas.height = height * d;
      ctx.setTransform(d, 0, 0, d, 0, 0);
      if (!animating) draw();
    };
    const onPref = () => {
      const next = !rm.matches;
      if (next === animating) return;
      animating = next;
      syncRepaint();
      cancelAnimationFrame(animId);
      draw();
    };
    window.addEventListener("resize", resize);
    rm.addEventListener?.("change", onPref);
    syncRepaint();
    resize();
    draw();
    return () => {
      repaint.current = null;
      window.removeEventListener("resize", resize);
      rm.removeEventListener?.("change", onPref);
      cancelAnimationFrame(animId);
    };
  }, []);

  return <canvas ref={canvasRef} className="ob-canvas" aria-hidden="true" />;
}
