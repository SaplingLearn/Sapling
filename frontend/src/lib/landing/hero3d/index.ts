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
 * The rig is scroll-driven only. As the hero leaves, the panels spread apart
 * and fade; they deliberately do NOT scale down.
 */

import * as THREE from 'three';
import { CARD_H, CARD_W, drawHeroCard, type CardKind } from './cardTexture';

/** Panel width in world units; height follows the texture's aspect. */
const CW = 1.88;
const CH = CW * (CARD_H / CARD_W);

/** Where each panel sits: card kind, position, rotation, scale. */
const LAYOUT: { kind: CardKind; pos: [number, number, number]; rot: [number, number, number]; scale: number }[] = [
  { kind: 1, pos: [1.90, 1.50, -0.25], rot: [0.05, -0.26, -0.04], scale: 1.02 },
  { kind: 0, pos: [-0.20, -0.45, 0.70], rot: [0.06, 0.11, 0.032], scale: 0.88 },
  { kind: 2, pos: [4.15, 1.85, -2.55], rot: [0.04, -0.36, 0.05], scale: 1.05 },
  { kind: 3, pos: [-3.28, 0.60, -1.00], rot: [0.05, 0.30, -0.05], scale: 0.90 },
  { kind: 4, pos: [1.30, 2.15, -3.00], rot: [-0.05, -0.14, 0.03], scale: 1.00 },
];

/** Below this width the whole rig shrinks so it clears the copy. */
const NARROW_PX = 1100;
/** Cap the pixel ratio — the panels are soft-focus, so 1.75 is indistinguishable from 3. */
const MAX_DPR = 1.75;

export interface HeroRig {
  stop(): void;
}

/**
 * Mounts the rig on `canvas`.
 *
 * `getMouse` returns pointer position in -1..1 on both axes; `getParallax`
 * is the 0..2 intensity multiplier. Returns null when WebGL is unavailable,
 * so the caller can simply leave the canvas blank.
 */
export function startHeroRig(
  canvas: HTMLCanvasElement,
  getMouse: () => { x: number; y: number },
  getParallax: () => number,
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
  const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 200);
  camera.position.set(0, 0, 7.6);

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
    const intensity = getParallax();
    const sp = Math.max(0, Math.min(1, window.scrollY / vh));
    const ease = sp * sp * (3 - 2 * sp);
    // never reaches 0 — a sliver stays lit as the descent band takes over
    const fade = 1 - ease * 0.92;

    scene.position.y = -ease * 1.5 * intensity;
    scene.rotation.x = ease * 0.13 * intensity;

    const { x: mx, y: my } = getMouse();

    // whole-rig pointer lean, critically damped toward the target
    group.rotation.y += (mx * 0.13 - group.rotation.y) * Math.min(1, dt * 2.2);
    group.rotation.x += (my * 0.09 - group.rotation.x) * Math.min(1, dt * 2.2);
    group.position.x += (-mx * 0.34 - group.position.x) * Math.min(1, dt * 2.0);
    group.position.y += (my * 0.24 - group.position.y) * Math.min(1, dt * 2.0);

    panels.forEach((p) => {
      const s = t * 0.32 + p.phase;
      p.grp.position.y = p.base.pos[1] + Math.sin(s) * 0.18;
      // the `* ease * 0.22` term is the separation: each panel drifts further
      // out along its own x as the hero scrolls away. Scale is untouched.
      p.grp.position.x = p.base.pos[0] + Math.cos(s * 0.72) * 0.09 + p.base.pos[0] * ease * 0.22;
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
