/**
 * Hero background canvas — a slowly rotating 3D point cloud.
 *
 * Ported from `Sapling Landing v4.dc.html` (unchanged there since v2). Owns
 * its own rAF and resize listener, and self-gates once the hero is more than
 * a viewport off-screen so it costs nothing for the rest of the page.
 */

import type { Mouse } from './ambient';

/** Weighted palette — the cloud is mostly cool, with coral for contrast. */
const PALETTE: { c: string; w: number }[] = [
  { c: '#8A63D2', w: 0.24 },
  { c: '#3e6f8a', w: 0.24 },
  { c: '#E27A63', w: 0.2 },
  { c: '#14B8A6', w: 0.15 },
  { c: '#9CA3AF', w: 0.1 },
  { c: '#D1D5DB', w: 0.07 },
];

const CLUSTERS = [
  { x: -600, y: -250, z: 80 }, { x: -350, y: -100, z: -120 },
  { x: -100, y: -300, z: 200 }, { x: 150, y: -150, z: -80 },
  { x: 400, y: -250, z: 150 }, { x: 600, y: -100, z: -50 },
  { x: -500, y: 100, z: -150 }, { x: -200, y: 200, z: 100 },
  { x: 50, y: 150, z: -200 }, { x: 300, y: 250, z: 120 },
  { x: 550, y: 150, z: -100 }, { x: -400, y: 350, z: 60 },
  { x: 0, y: 0, z: 0 }, { x: 200, y: -50, z: -150 },
];

const SPREAD = 280;
const COUNT = 150;
/** Focal length for the perspective divide. */
const FL = 1000;

export interface HeroCanvas {
  stop(): void;
}

export function startHeroCanvas(
  canvas: HTMLCanvasElement,
  getMouse: () => Mouse,
  getParallaxY: () => number,
): HeroCanvas | null {
  const ctx = canvas.getContext('2d', { alpha: true });
  if (!ctx) return null;

  let width = 0;
  let height = 0;
  let rotAngle = 0;
  let raf = 0;

  const randColor = () => {
    const r = Math.random();
    let s = 0;
    for (const p of PALETTE) {
      s += p.w;
      if (r <= s) return p.c;
    }
    return PALETTE[0].c;
  };

  const nodes = Array.from({ length: COUNT }, () => {
    const cl = CLUSTERS[Math.floor(Math.random() * CLUSTERS.length)];
    return {
      ox: cl.x + (Math.random() - 0.5) * SPREAD,
      oy: cl.y + (Math.random() - 0.5) * SPREAD,
      oz: cl.z + (Math.random() - 0.5) * SPREAD,
      color: randColor(),
      radius: 1 + Math.random() * 4,
      seed: Math.random() * 100,
    };
  });

  const resize = () => {
    const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    width = window.innerWidth;
    height = window.innerHeight;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  };
  window.addEventListener('resize', resize);
  resize();

  const draw = () => {
    raf = requestAnimationFrame(draw);
    // hero is well off-screen: keep the rAF alive but skip all the work
    if (window.scrollY > height * 1.05) return;

    ctx.clearRect(0, 0, width, height);
    rotAngle += 0.0008;
    const cx = width / 2;
    const cy = height / 2;
    const t = Date.now() * 0.001;
    const { x: mx, y: my } = getMouse();
    const parallaxY = getParallaxY();

    const proj = nodes
      .map((n) => {
        const ny = n.oy + Math.sin(t * 0.4 + n.seed) * 15;
        let x = n.ox * Math.cos(rotAngle) - n.oz * Math.sin(rotAngle);
        const z = n.oz * Math.cos(rotAngle) + n.ox * Math.sin(rotAngle);
        // mouse pull scales with depth, so near points swing further
        x -= mx * (z + FL) * 0.02;
        const y2 = ny - my * (z + FL) * 0.02;
        const sc = FL / (FL + z);
        return { x: x * sc + cx, y: y2 * sc + cy - parallaxY, z, sc, n };
      })
      .sort((a, b) => b.z - a.z);

    // Link pass: sort by x so the inner loop can break as soon as dx
    // exceeds reach, turning O(n²) into something near-linear.
    ctx.lineWidth = 0.5;
    const byX = proj.slice().sort((a, b) => a.x - b.x);
    for (let i = 0; i < byX.length; i++) {
      const p1 = byX[i];
      const reach = 70 * p1.sc;
      for (let j = i + 1; j < byX.length; j++) {
        const p2 = byX[j];
        const dx = p2.x - p1.x;
        if (dx > reach) break;
        const dy = p2.y - p1.y;
        const d2 = dx * dx + dy * dy;
        if (d2 < reach * reach) {
          const a = (1 - Math.sqrt(d2) / reach) * 0.15 * Math.min(1, p1.sc);
          if (a > 0.002) {
            ctx.strokeStyle = 'rgba(156,163,175,' + a.toFixed(3) + ')';
            ctx.beginPath();
            ctx.moveTo(p1.x, p1.y);
            ctx.lineTo(p2.x, p2.y);
            ctx.stroke();
          }
        }
      }
    }

    proj.forEach((p) => {
      if (p.z > -FL) {
        const breathe = 0.92 + 0.08 * Math.sin(t * 0.6 + p.n.seed);
        const fogA = p.z > 500 ? Math.max(0, 1 - (p.z - 500) / 500) : 1;
        const r = p.n.radius * p.sc * breathe;
        if (r > 0.1) {
          ctx.globalAlpha = fogA;
          ctx.beginPath();
          ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
          ctx.fillStyle = p.n.color;
          ctx.fill();
        }
      }
    });
    ctx.globalAlpha = 1;
  };

  draw();

  return {
    stop() {
      if (raf) cancelAnimationFrame(raf);
      window.removeEventListener('resize', resize);
    },
  };
}
