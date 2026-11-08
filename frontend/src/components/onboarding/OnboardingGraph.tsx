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
import { createChapterLayer, type GraphPhase, type GraphZoom } from "./chapterLayer";

export type { GraphPhase, GraphZoom };

interface Props {
  phase: GraphPhase;
  zoom: GraphZoom;
  activeChapter: number;
  completed: number[];
  /** Rotation speed multiplier (design default 0.5). */
  speed?: number;
}

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
const FL = 1000;

interface AmbientNode { ox: number; oy: number; oz: number; pi: number; hc: number; radius: number; seed: number }
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
    const layer = createChapterLayer();
    let curZoom = 1;
    let clusterProgress = 0;
    let width = 0, height = 0, rot = 0, animId = 0, lastMs = 0;

    const draw = () => {
      ctx.clearRect(0, 0, width, height);
      const cx = width / 2, cy = height / 2, nowMs = performance.now(), t = nowMs * 0.001;
      const dtF = lastMs ? Math.min(4, (nowMs - lastMs) / 16.667) : 1;
      lastMs = nowMs;
      rot += 0.0008 * live.current.speed * dtF;
      ({ zoom: curZoom, clusterProgress } = layer.step(nowMs, dtF, live.current));
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
      layer.draw(ctx, nowMs, t, rot, cx, cy);
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
