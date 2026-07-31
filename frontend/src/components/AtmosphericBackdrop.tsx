"use client";

/**
 * Sapling atmospheric backdrop.
 *
 * Per .impeccable.md: "very subtle, barely-there colorful orbs drifting
 * slowly in 3D space… warm, atmospheric palette (soft blues, purples,
 * ambers, teals) at very low opacity — you feel them more than you see
 * them. The effect is atmospheric ambience, not decoration."
 *
 * Implementation notes:
 *  - Single <canvas> at z-index 0, position: fixed, behind all UI chrome.
 *  - DPR-aware; redraws on window resize.
 *  - 14 orbs, each with a slow 2D drift + pseudo-depth via scale + opacity.
 *  - Opacity capped at 0.10; you feel them more than you see them.
 *  - Honors prefers-reduced-motion: paints one still frame, never animates.
 *  - Palette is intentionally independent of the UI green so the brand's
 *    accent keeps its exclusive semantic meaning (growth/mastery).
 */

import React from "react";
import { IS_TEST_MODE, random } from "@/lib/testMode";

type Orb = {
  x: number; y: number; z: number;
  vx: number; vy: number;
  r: number;
  color: string;
  phase: number;
};

// Warm, atmospheric palette — blues, purples, ambers, teals. Green is
// reserved for UI branding, so it's intentionally absent here.
const PALETTE = [
  "#9bb2d1", // soft blue
  "#b4a7cc", // muted lilac
  "#e0c7a1", // warm amber
  "#9ec7c1", // dusty teal
  "#d4b3b0", // faded rose
  "#b8c9a6", // pale sage-adjacent (barely, for continuity)
];

/** The painted radius of an orb — fixed for its lifetime (r and z never change). */
function orbRadius(orb: Orb) {
  return orb.r * (0.7 + orb.z * 0.6);
}

/** ~30fps. Ambient drift does not need a frame the eye can't distinguish. */
const FRAME_MS = 1000 / 30;

/**
 * Pre-render one orb's radial gradient into its own offscreen canvas.
 *
 * Everything the gradient depends on — colour, radius, depth-derived alpha —
 * is fixed when the orb is created; only x/y move. Baking once turns the
 * per-frame cost from "build 14 gradients and fill 14 arcs" into "blit 14
 * bitmaps", which is the whole point: this backdrop is mounted app-wide, in
 * both ShellFrame layouts, behind every screen.
 */
function bakeOrb(orb: Orb, dpr: number): HTMLCanvasElement {
  const rad = orbRadius(orb);
  const alpha = 0.035 + orb.z * 0.07;
  const size = Math.max(1, Math.ceil(rad * 2 * dpr));
  const c = document.createElement("canvas");
  c.width = size;
  c.height = size;
  const cx = c.getContext("2d");
  if (cx) {
    cx.scale(dpr, dpr);
    const grad = cx.createRadialGradient(rad, rad, 0, rad, rad, rad);
    grad.addColorStop(0, hexToRgba(orb.color, alpha));
    grad.addColorStop(0.55, hexToRgba(orb.color, alpha * 0.45));
    grad.addColorStop(1, hexToRgba(orb.color, 0));
    cx.fillStyle = grad;
    cx.beginPath();
    cx.arc(rad, rad, rad, 0, Math.PI * 2);
    cx.fill();
  }
  return c;
}

function makeOrbs(width: number, height: number): Orb[] {
  const count = 14;
  const orbs: Orb[] = [];
  for (let i = 0; i < count; i++) {
    orbs.push({
      x: random() * width,
      y: random() * height,
      z: 0.35 + random() * 0.65,    // pseudo-depth 0.35..1
      vx: (random() - 0.5) * 0.12,  // very slow horizontal drift
      vy: (random() - 0.5) * 0.08,  // even slower vertical
      r: 180 + random() * 260,      // big, soft radial glows
      color: PALETTE[i % PALETTE.length],
      phase: random() * Math.PI * 2,
    });
  }
  return orbs;
}

export function AtmosphericBackdrop() {
  const canvasRef = React.useRef<HTMLCanvasElement | null>(null);
  const rafRef = React.useRef<number | null>(null);
  const orbsRef = React.useRef<Orb[]>([]);
  const sizeRef = React.useRef<{ w: number; h: number; dpr: number }>({ w: 0, h: 0, dpr: 1 });
  const reducedMotionRef = React.useRef<boolean>(false);
  /** One pre-rendered gradient bitmap per orb; see bakeOrb. */
  const spritesRef = React.useRef<HTMLCanvasElement[]>([]);
  const spriteDprRef = React.useRef<number>(0);
  const lastPaintRef = React.useRef<number>(0);

  React.useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const mql = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    // Test mode paints one still frame with seeded orbs — same path as
    // prefers-reduced-motion.
    reducedMotionRef.current = IS_TEST_MODE || !!mql?.matches;
    const onReducedChange = () => { reducedMotionRef.current = IS_TEST_MODE || !!mql?.matches; };
    mql?.addEventListener?.("change", onReducedChange);

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = window.innerWidth;
      const h = window.innerHeight;
      sizeRef.current = { w, h, dpr };
      canvas.width = Math.floor(w * dpr);
      canvas.height = Math.floor(h * dpr);
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      if (orbsRef.current.length === 0) orbsRef.current = makeOrbs(w, h);
      // Bake once, and again only if the device pixel ratio actually changes
      // (dragging the window to a different-density display). Orb radii do
      // not depend on viewport size, so a plain resize reuses the sprites.
      if (spritesRef.current.length !== orbsRef.current.length || spriteDprRef.current !== dpr) {
        spritesRef.current = orbsRef.current.map((orb) => bakeOrb(orb, dpr));
        spriteDprRef.current = dpr;
      }
    };
    resize();
    window.addEventListener("resize", resize);

    const paint = (t: number) => {
      // Ambient drift at 60fps buys nothing — these orbs move well under a
      // pixel per frame. Halving the rate halves the whole cost of the
      // backdrop, app-wide. `t === 0` is the reduced-motion still frame,
      // which must always paint.
      if (t && t - lastPaintRef.current < FRAME_MS) {
        rafRef.current = requestAnimationFrame(paint);
        return;
      }
      lastPaintRef.current = t;

      const { w, h } = sizeRef.current;
      ctx.clearRect(0, 0, w, h);

      // The pale-green background tint preserved — the backdrop must NOT
      // paint a big opaque fill; the page's own --bg shows through.
      const sprites = spritesRef.current;
      orbsRef.current.forEach((orb, i) => {
        const sprite = sprites[i];
        if (!sprite) return;
        const rad = orbRadius(orb);
        // Peak opacity 0.10 on the closest orbs; falls off with depth — both
        // already baked into the sprite.
        ctx.drawImage(sprite, orb.x - rad, orb.y - rad, rad * 2, rad * 2);
      });

      if (reducedMotionRef.current) return;

      // Slow drift. Wrap orbs that float past the edges (with a soft margin
      // so they don't pop in — the gradient tail handles the fade).
      for (const orb of orbsRef.current) {
        orb.phase += 0.0008;
        orb.x += orb.vx + Math.cos(orb.phase) * 0.04;
        orb.y += orb.vy + Math.sin(orb.phase * 0.8) * 0.03;
        const m = orb.r;
        if (orb.x < -m) orb.x = w + m;
        else if (orb.x > w + m) orb.x = -m;
        if (orb.y < -m) orb.y = h + m;
        else if (orb.y > h + m) orb.y = -m;
      }

      rafRef.current = requestAnimationFrame(paint);
    };

    if (reducedMotionRef.current) {
      // Paint one still frame only.
      paint(0);
    } else {
      rafRef.current = requestAnimationFrame(paint);
    }

    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
      window.removeEventListener("resize", resize);
      mql?.removeEventListener?.("change", onReducedChange);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden
      style={{
        position: "fixed",
        inset: 0,
        width: "100vw",
        height: "100vh",
        pointerEvents: "none",
        zIndex: 0,
      }}
    />
  );
}

function hexToRgba(hex: string, alpha: number): string {
  const h = hex.replace("#", "");
  const bigint = parseInt(h.length === 3 ? h.split("").map(c => c + c).join("") : h, 16);
  const r = (bigint >> 16) & 255;
  const g = (bigint >> 8) & 255;
  const b = bigint & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}
