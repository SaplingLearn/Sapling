/**
 * Ambient constellation — the fixed z-index:-1 canvas behind everything.
 *
 * Ported from `Sapling Landing v4.dc.html`. Fades in past half a viewport of
 * scroll, then drifts on a parallax depth per node with a little mouse pull.
 * Nodes wrap vertically, so the field is endless without ever reallocating.
 *
 * `fade` is computed and time-eased by the engine rather than derived from
 * the scroll position here: positions must track the scroll 1:1 (a lagged
 * position reads as drag), but opacity popping with it reads as a glitch —
 * so the two are deliberately decoupled.
 */

import { cv } from './dom';

const PALETTE = ['#0E9E5A', '#4FA574', '#8FD9A8', '#0C5638', '#9CA3AF'];

/** Squared link distance — 110px, pre-squared to keep it out of the loop. */
const LINK_D2 = 12100;
const LINK_D = 110;

export interface AmbientNode {
  /** Fractional position across the viewport. */
  fx: number;
  fy: number;
  /** Parallax depth, 0.15..0.6. */
  depth: number;
  r: number;
  color: string;
  seed: number;
  /** A few render as leaves rather than dots. */
  leaf: boolean;
}

export interface Mouse {
  x: number;
  y: number;
}

export interface AmbientField {
  nodes: AmbientNode[];
  draw(canvas: HTMLCanvasElement, sy: number, vh: number, mouse: Mouse, fade: number): void;
}

export function createAmbient(): AmbientField {
  const nodes: AmbientNode[] = Array.from({ length: 46 }, () => ({
    fx: Math.random(),
    fy: Math.random() * 1.15 - 0.05,
    depth: 0.15 + Math.random() * 0.45,
    r: 1.4 + Math.random() * 2.6,
    color: PALETTE[Math.floor(Math.random() * PALETTE.length)],
    seed: Math.random() * 100,
    leaf: Math.random() < 0.14,
  }));

  function draw(canvas: HTMLCanvasElement, sy: number, vh: number, mouse: Mouse, fade: number): void {
    const c = cv(canvas);
    const { ctx, w, h } = c;
    ctx.clearRect(0, 0, w, h);

    if (fade <= 0.01) return;

    const t = Date.now() * 0.001;
    const mx = mouse.x;
    const my = mouse.y;
    const span = h + 400;

    const pts = nodes.map((n) => {
      // wrap into [-200, h+200) so nodes recycle instead of running out
      const y = (((n.fy * span - sy * n.depth) % span) + span) % span - 200;
      const x = n.fx * w + Math.sin(t * 0.3 + n.seed) * 14 - mx * 26 * n.depth;
      return { x, y: y + Math.cos(t * 0.24 + n.seed) * 10 - my * 18 * n.depth, n };
    });

    ctx.lineWidth = 0.6;
    for (let i = 0; i < pts.length; i++) {
      for (let j = i + 1; j < pts.length; j++) {
        const dx = pts[i].x - pts[j].x;
        const dy = pts[i].y - pts[j].y;
        if (dx * dx + dy * dy < LINK_D2) {
          const d = Math.sqrt(dx * dx + dy * dy);
          ctx.strokeStyle = 'rgba(79,165,116,' + (fade * 0.1 * (1 - d / LINK_D)).toFixed(3) + ')';
          ctx.beginPath();
          ctx.moveTo(pts[i].x, pts[i].y);
          ctx.lineTo(pts[j].x, pts[j].y);
          ctx.stroke();
        }
      }
    }

    pts.forEach((pt) => {
      ctx.globalAlpha = fade * (0.2 + 0.12 * Math.sin(t * 0.8 + pt.n.seed));
      if (pt.n.leaf) {
        ctx.save();
        ctx.translate(pt.x, pt.y);
        ctx.rotate(Math.sin(t * 0.2 + pt.n.seed) * 0.6);
        ctx.fillStyle = pt.n.color;
        ctx.beginPath();
        ctx.moveTo(0, -5);
        ctx.quadraticCurveTo(4.5, -1, 0, 6);
        ctx.quadraticCurveTo(-4.5, -1, 0, -5);
        ctx.fill();
        ctx.restore();
      } else {
        ctx.beginPath();
        ctx.arc(pt.x, pt.y, pt.n.r, 0, Math.PI * 2);
        ctx.fillStyle = pt.n.color;
        ctx.fill();
      }
    });
    ctx.globalAlpha = 1;
  }

  return { nodes, draw };
}
