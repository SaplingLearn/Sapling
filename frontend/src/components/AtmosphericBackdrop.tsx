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
 *  - Each orb's radial gradient is pre-baked to an offscreen sprite (#111);
 *    frames composite bitmaps via drawImage. Re-baked only on DPR change.
 *  - The RAF loop is throttled to ~30fps (imperceptible on this slow drift)
 *    and pauses entirely while the tab is hidden.
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
  // Pre-baked gradient sprite; re-baked only when the DPR changes (#111).
  sprite?: HTMLCanvasElement;
};

// ~30fps frame budget — plenty for a slow ambient drift (#111).
const FRAME_MS = 1000 / 30;
const SPRITE_MAX_PX = 512;

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

// Pre-bake one orb's radial gradient to an offscreen canvas so the animation
// loop composites bitmaps with drawImage instead of re-creating full-viewport
// gradients every frame (#111). Radius/alpha are fixed at orb creation, so
// only a DPR change invalidates a sprite.
function bakeSprite(orb: Orb, dpr: number): HTMLCanvasElement | undefined {
  const rad = orb.r * (0.7 + orb.z * 0.6);
  // Peak opacity 0.10 on the closest orbs; falls off with depth.
  const alpha = 0.035 + orb.z * 0.07;
  // Cap the sprite's backing resolution: at full device resolution the 14
  // sprites cost ~100 MB of canvas memory at DPR 2 (#490 review). The
  // gradients are soft, so drawImage upscaling from a capped sprite is
  // visually indistinguishable at a fraction of the memory.
  const size = Math.max(1, Math.min(Math.ceil(rad * 2 * dpr), SPRITE_MAX_PX));
  const sprite = document.createElement("canvas");
  sprite.width = size;
  sprite.height = size;
  const sctx = sprite.getContext("2d");
  if (!sctx) return undefined;
  const c = size / 2;
  const grad = sctx.createRadialGradient(c, c, 0, c, c, c);
  grad.addColorStop(0, hexToRgba(orb.color, alpha));
  grad.addColorStop(0.55, hexToRgba(orb.color, alpha * 0.45));
  grad.addColorStop(1, hexToRgba(orb.color, 0));
  sctx.fillStyle = grad;
  sctx.fillRect(0, 0, size, size);
  return sprite;
}

export function AtmosphericBackdrop() {
  const canvasRef = React.useRef<HTMLCanvasElement | null>(null);
  const rafRef = React.useRef<number | null>(null);
  const orbsRef = React.useRef<Orb[]>([]);
  const sizeRef = React.useRef<{ w: number; h: number; dpr: number }>({ w: 0, h: 0, dpr: 1 });
  const reducedMotionRef = React.useRef<boolean>(false);
  const bakedDprRef = React.useRef<number | null>(null);
  const lastFrameRef = React.useRef<number | null>(null);

  React.useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const mql = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    // Test mode paints one still frame with seeded orbs — same path as
    // prefers-reduced-motion.
    reducedMotionRef.current = IS_TEST_MODE || !!mql?.matches;
    const onReducedChange = () => {
      reducedMotionRef.current = IS_TEST_MODE || !!mql?.matches;
      // Un-reducing must revive the loop explicitly: tick() parks itself on a
      // still frame when reduced (the old always-running loop resumed
      // implicitly, so without this the backdrop would stay frozen).
      if (!reducedMotionRef.current && rafRef.current == null && !document.hidden) {
        lastFrameRef.current = null;
        rafRef.current = requestAnimationFrame(tick);
      }
    };
    mql?.addEventListener?.("change", onReducedChange);

    const drawFrame = () => {
      const { w, h } = sizeRef.current;
      ctx.clearRect(0, 0, w, h);

      // The pale-green background tint preserved — the backdrop must NOT
      // paint a big opaque fill; the page's own --bg shows through. Each
      // orb's gradient is pre-baked (see bakeSprite), so a frame is pure
      // bitmap compositing.
      for (const orb of orbsRef.current) {
        if (!orb.sprite) continue;
        const rad = orb.r * (0.7 + orb.z * 0.6);
        ctx.drawImage(orb.sprite, orb.x - rad, orb.y - rad, rad * 2, rad * 2);
      }
    };

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
      // Orb sizes are fixed at creation, so a DPR change is the only thing
      // that invalidates the pre-baked sprites.
      if (bakedDprRef.current !== dpr) {
        for (const orb of orbsRef.current) orb.sprite = bakeSprite(orb, dpr);
        bakedDprRef.current = dpr;
      }
      // Setting canvas.width cleared the backing store; when the loop is
      // parked (reduced motion) nothing else repaints, so do it here.
      if (reducedMotionRef.current) drawFrame();
    };
    resize();
    window.addEventListener("resize", resize);

    // Slow drift, scaled by elapsed 60fps-equivalent frames so the ~30fps
    // throttle keeps the same drift speed as the old per-frame step. Wrap
    // orbs that float past the edges (with a soft margin so they don't pop
    // in — the gradient tail handles the fade).
    const step = (dtFrames: number) => {
      const { w, h } = sizeRef.current;
      for (const orb of orbsRef.current) {
        orb.phase += 0.0008 * dtFrames;
        orb.x += (orb.vx + Math.cos(orb.phase) * 0.04) * dtFrames;
        orb.y += (orb.vy + Math.sin(orb.phase * 0.8) * 0.03) * dtFrames;
        const m = orb.r;
        if (orb.x < -m) orb.x = w + m;
        else if (orb.x > w + m) orb.x = -m;
        if (orb.y < -m) orb.y = h + m;
        else if (orb.y > h + m) orb.y = -m;
      }
    };

    const tick = (t: number) => {
      if (reducedMotionRef.current) {
        // Paint one still frame only.
        drawFrame();
        rafRef.current = null;
        return;
      }
      rafRef.current = requestAnimationFrame(tick);
      const last = lastFrameRef.current;
      // Throttle to ~30fps; the 1ms epsilon keeps 60Hz displays from
      // slipping to every third frame on timestamp jitter.
      if (last != null && t - last < FRAME_MS - 1) return;
      // Clamp catch-up so a long RAF gap can't teleport the orbs.
      const dtFrames = last == null ? 1 : Math.min((t - last) / (1000 / 60), 4);
      lastFrameRef.current = t;
      drawFrame();
      step(dtFrames);
    };

    // Repainting a hidden tab is pure waste — pause the loop entirely and
    // resume (without integrating the hidden gap into the drift) when the
    // tab becomes visible again.
    const onVisibility = () => {
      if (document.hidden) {
        if (rafRef.current != null) {
          cancelAnimationFrame(rafRef.current);
          rafRef.current = null;
        }
      } else if (!reducedMotionRef.current && rafRef.current == null) {
        lastFrameRef.current = null;
        rafRef.current = requestAnimationFrame(tick);
      }
    };
    document.addEventListener("visibilitychange", onVisibility);

    if (reducedMotionRef.current) {
      // Paint one still frame only.
      drawFrame();
    } else {
      rafRef.current = requestAnimationFrame(tick);
    }

    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
      window.removeEventListener("resize", resize);
      document.removeEventListener("visibilitychange", onVisibility);
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
