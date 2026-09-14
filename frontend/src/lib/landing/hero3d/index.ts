/**
 * The hero's WebGL panel rig.
 *
 * Ported from `_initHero3D` in `Sapling Landing v5.dc.html`, which builds
 * three exclusive scenes cross-faded by a `heroMode` weight: floating product
 * panels (0), an orbitable knowledge constellation (1), and a shader growth
 * field (2).
 *
 * Only mode 0 is ported, because only mode 0 can ever be seen. The source
 * exposes `setHero0/1/2` and the mode pills from `renderVals()`, but no
 * markup in the file references any of them, so `heroMode` is pinned at 0 for
 * the life of the page and the other two scenes — several hundred lines of
 * GLSL — are unreachable. Porting them would be porting dead code. If a mode
 * switcher is ever added back, they are recoverable from the source file.
 *
 * The rig is scroll-driven only. The panels ride the scroll on exactly the
 * same curve as the DOM copy — see `getHeroShiftPx` below — and fade as the
 * hero leaves. They deliberately do NOT scale down.
 */

import * as THREE from 'three';
import { CARD_H, CARD_W, drawHeroCard, type CardKind } from './cardTexture';

/** Panel width in world units; height follows the texture's aspect. */
const CW = 2.02;
const CH = CW * (CARD_H / CARD_W);

/** Camera distance from the origin plane, on -Z. */
const CAM_Z = 7.6;
const FOV = 42;
const TAN_HALF_FOV = Math.tan((FOV * Math.PI) / 360);

/**
 * Where each panel sits: card kind, position, rotation, scale.
 *
 * The two back panels used to sit at z −2.55 and −3.00, which projected their
 * 460px-wide card bodies down to ~170 CSS px — a 0.37x downscale that put all
 * their body copy under 7px and made it unreadable. They are pulled forward,
 * with x/y divided by the same factor the distance shrank by, so each panel
 * lands on precisely the same screen position as before and only grows.
 */
const LAYOUT: { kind: CardKind; pos: [number, number, number]; rot: [number, number, number]; scale: number }[] = [
  { kind: 1, pos: [1.90, 1.50, -0.25], rot: [0.05, -0.26, -0.04], scale: 1.02 },
  { kind: 0, pos: [-0.20, -0.45, 0.70], rot: [0.06, 0.11, 0.032], scale: 0.88 },
  { kind: 2, pos: [3.70, 1.65, -1.45], rot: [0.04, -0.36, 0.05], scale: 1.05 },
  { kind: 3, pos: [-3.13, 0.57, -0.60], rot: [0.05, 0.30, -0.05], scale: 0.90 },
  { kind: 4, pos: [1.15, 1.90, -1.75], rot: [-0.05, -0.14, 0.03], scale: 1.00 },
];

/** Below this width the whole rig shrinks so it clears the copy. */
const NARROW_PX = 1100;
/**
 * Cap the pixel ratio.
 *
 * This was 1.75 on the reasoning that the panels are soft-focus, so a higher
 * ratio buys nothing. They are not soft-focus — the card copy is meant to be
 * read — so on a HiDPI screen the cap was throwing away the density that makes
 * the small type legible. 3 covers every panel a real display uses.
 */
const MAX_DPR = 3;

export interface HeroRig {
  stop(): void;
}

/**
 * Mounts the rig on `canvas`.
 *
 * `getMouse` returns pointer position in -1..1 on both axes. `getHeroShiftPx`
 * returns the very number the engine has just written into the hero copy's
 * `translateY` — negative as the copy rides up — so the panels can be moved by
 * the identical screen distance instead of running a scroll curve of their
 * own. Returns null when WebGL is unavailable, so the caller can simply leave
 * the canvas blank.
 */
export function startHeroRig(
  canvas: HTMLCanvasElement,
  getMouse: () => { x: number; y: number },
  getHeroShiftPx: () => number,
): HeroRig | null {
  let renderer: THREE.WebGLRenderer;
  try {
    renderer = new THREE.WebGLRenderer({
      canvas, antialias: true, alpha: true, powerPreference: 'high-performance',
    });
  } catch {
    return null;
  }
  renderer.setClearColor(0x000000, 0);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(FOV, 1, 0.1, 200);
  camera.position.set(0, 0, CAM_Z);

  const group = new THREE.Group();
  scene.add(group);

  const maxAniso = renderer.capabilities.getMaxAnisotropy();
  const panels = LAYOUT.map((L, i) => {
    const tex = new THREE.CanvasTexture(drawHeroCard(L.kind));
    tex.anisotropy = Math.min(8, maxAniso);
    const mesh = new THREE.Mesh(
      new THREE.PlaneGeometry(CW, CH),
      new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false }),
    );
    mesh.scale.setScalar(L.scale);
    const grp = new THREE.Group();
    grp.add(mesh);
    grp.position.set(...L.pos);
    grp.rotation.set(...L.rot);
    group.add(grp);
    return {
      grp, tex, kind: L.kind, base: L,
      mat: mesh.material as THREE.MeshBasicMaterial,
      // irrational-ish stagger so the five bob cycles never sync up
      phase: i * 1.31,
    };
  });

  // ── sizing ──────────────────────────────────────────────────────────
  const resize = () => {
    const w = canvas.clientWidth || window.innerWidth;
    const h = canvas.clientHeight || window.innerHeight;
    const dpr = Math.min(window.devicePixelRatio || 1, MAX_DPR);
    renderer.setPixelRatio(dpr);
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    const s = w < NARROW_PX ? 0.72 : 1;
    panels.forEach((p) => p.grp.scale.setScalar(s));
  };
  resize();
  window.addEventListener('resize', resize);

  // Webfont metrics change the wrapped copy, so repaint once they're ready.
  let disposed = false;
  if (document.fonts?.ready) {
    document.fonts.ready.then(() => {
      if (disposed) return;
      panels.forEach((p) => {
        p.tex.image = drawHeroCard(p.kind);
        p.tex.needsUpdate = true;
      });
    });
  }

  // ── loop ────────────────────────────────────────────────────────────
  let raf = 0;
  let last = performance.now();
  let t = 0;

  const tick = (now: number) => {
    raf = requestAnimationFrame(tick);
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;

    // the rig is only ever on screen through the first viewport-and-a-bit
    const vh = window.innerHeight || 1;
    if (window.scrollY > vh * 1.35) return;

    t += dt;

    // The copy's scroll offset in CSS px (negative = risen). Everything below
    // is derived from it, so the panels and the copy share one scroll curve —
    // including its double-lerp smoothing — rather than two that drift apart.
    const shiftPx = getHeroShiftPx();
    const vpH = canvas.clientHeight || vh;
    // the copy's own factor is 0.3, so a full viewport of scroll lifts it 0.3vh
    const progress = Math.max(0, Math.min(1, -shiftPx / (0.3 * vh)));
    // never reaches 0 — a sliver stays lit as the descent band takes over
    const fade = 1 - progress * 0.92;

    const { x: mx, y: my } = getMouse();

    // whole-rig pointer lean, critically damped toward the target
    group.rotation.y += (mx * 0.13 - group.rotation.y) * Math.min(1, dt * 2.2);
    group.rotation.x += (my * 0.09 - group.rotation.x) * Math.min(1, dt * 2.2);
    group.position.x += (-mx * 0.34 - group.position.x) * Math.min(1, dt * 2.0);
    group.position.y += (my * 0.24 - group.position.y) * Math.min(1, dt * 2.0);

    panels.forEach((p) => {
      const s = t * 0.32 + p.phase;
      // World units that span one screen pixel at this panel's depth. Each
      // panel needs its own factor: they sit at different z, and a single
      // scene-level offset would move the near ones further than the far ones.
      const worldPerPx = (2 * (CAM_Z - p.base.pos[2]) * TAN_HALF_FOV) / vpH;
      p.grp.position.y = p.base.pos[1] + Math.sin(s) * 0.18 - shiftPx * worldPerPx;
      p.grp.position.x = p.base.pos[0] + Math.cos(s * 0.72) * 0.09;
      p.grp.position.z = p.base.pos[2];
      p.grp.rotation.z = p.base.rot[2] + Math.sin(s * 0.55) * 0.022;
      p.grp.rotation.x = p.base.rot[0] + Math.sin(s * 0.63) * 0.03;
      p.mat.opacity = fade;
    });

    camera.position.x += (mx * 0.16 - camera.position.x) * Math.min(1, dt * 1.6);
    camera.position.y += (-my * 0.11 - camera.position.y) * Math.min(1, dt * 1.6);
    camera.lookAt(0, 0, 0);

    renderer.render(scene, camera);
  };
  raf = requestAnimationFrame(tick);

  return {
    stop() {
      disposed = true;
      cancelAnimationFrame(raf);
      window.removeEventListener('resize', resize);
      panels.forEach((p) => {
        p.tex.dispose();
        p.mat.dispose();
        p.grp.children.forEach((ch) => {
          if (ch instanceof THREE.Mesh) ch.geometry.dispose();
        });
      });
      renderer.dispose();
    },
  };
}
