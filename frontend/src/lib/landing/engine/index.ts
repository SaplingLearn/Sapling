/**
 * Master scroll engine.
 *
 * Ported from `Sapling Landing v4.dc.html`. One rAF loop reads scroll
 * progress and drives all three acts, the section nav, the ambient canvas,
 * the gallery marquee and the plant field. It never reads layout — that is
 * `measure()`'s job, throttled to ~1.6x/sec — and never writes an unchanged
 * style, because every write goes through `put()`.
 *
 * The hero canvas and the drag-field sim own separate loops; they gate
 * themselves on visibility rather than being driven from here.
 */

import { clamp01, smooth } from '../color';
import { createAmbient, type AmbientField, type Mouse } from './ambient';
import { put } from './dom';
import { createFlipState, type FlipState } from './flip';
import { buildGraph, type BuiltGraph } from './graph';
import {
  createGraphViewState, drawExplore, drawScroll,
  type GraphViewState,
} from './graphView';
import { createMarquee, type MarqueeController } from './marquee';
import { fitIngest, measure, type Measured, type ViewportCache } from './measure';
import { createPlantField, type PlantField } from './plant';
import { createSim, type SimController } from './sim';

/** How often the layout measure pass may run, in ms. */
const MEASURE_MS = 600;
/** Programmatic scrolls bypass smoothing for this long, so nav lands 1:1. */
const JUMP_MS = 1500;
/** Act I caption windows, as scroll-progress ranges. */
const ACT1_WINDOWS: [number, number][] = [[0.0, 0.22], [0.24, 0.47], [0.49, 0.73], [0.72, 1.01]];

export interface EngineRefs {
  root: HTMLElement | null;
  nav: HTMLElement | null;
  heroContent: HTMLElement | null;
  actCanvas: HTMLCanvasElement | null;
  ambientCanvas: HTMLCanvasElement | null;
  plantCanvas: HTMLCanvasElement | null;
  carousel: HTMLElement | null;
  ingestScene: HTMLElement | null;
  ingestStage: HTMLElement | null;
}

export interface EngineHooks {
  getExploring(): boolean;
  getExpOut(): boolean;
  getExpNode(): number | null;
  getTutorMode(): number;
  setTutorMode(v: number): void;
  getJumpOpen(): boolean;
  getPastHero(): boolean;
  setPastHero(v: boolean): void;
  getJumpDown(): boolean;
  setJumpDown(v: boolean): void;
  /** The `parallax` prop, 0..2. */
  getParallax(): number;
  onOpenGallery(index: number, from: HTMLElement | null): void;
  setMarqueeDragged(v: boolean): void;
}

export class LandingEngine {
  readonly graph: BuiltGraph = buildGraph();
  readonly view: GraphViewState = createGraphViewState();
  readonly ambient: AmbientField = createAmbient();
  readonly plant: PlantField = createPlantField();
  readonly flip: FlipState = createFlipState();
  readonly marquee: MarqueeController;
  readonly sim: SimController = createSim();

  mouse: Mouse = { x: 0, y: 0 };
  parallaxY = 0;

  private refs: EngineRefs;
  private hooks: EngineHooks;
  private raf = 0;
  private simRaf = 0;
  private M: Measured | null = null;
  private docH = 1;
  private measuredAt = 0;
  private vp: ViewportCache = { vw: -1, vh: -1 };

  // scroll smoothing
  private sySmooth: number | undefined;
  private syMedia = 0;
  private jumpUntil = 0;
  private lastJumpSy = 0;
  private jumpSettle = 0;

  // nav / jump pill
  private jumpLastY = 0;
  private jumpSeen = 0;
  private jumpOnDark: boolean | undefined;
  private activeNav = -1;

  // act state
  private rotCur = 0;
  private tutorFacing = -1;
  private tileCounts = [0, 0, 0, 0];

  constructor(refs: EngineRefs, hooks: EngineHooks) {
    this.refs = refs;
    this.hooks = hooks;
    this.marquee = createMarquee({
      onOpen: (i, el) => hooks.onOpenGallery(i, el),
      setDragged: (v) => hooks.setMarqueeDragged(v),
    });
  }

  /** Programmatic scrolls call this so smoothing doesn't fight them. */
  markJump(): void {
    this.jumpUntil = Date.now() + JUMP_MS;
  }

  start(): void {
    if (!this.raf) this.raf = requestAnimationFrame(this.tick);
    if (!this.simRaf) this.simRaf = requestAnimationFrame(this.simTick);
  }

  stop(): void {
    if (this.raf) cancelAnimationFrame(this.raf);
    if (this.simRaf) cancelAnimationFrame(this.simRaf);
    this.raf = 0;
    this.simRaf = 0;
    this.marquee.destroy();
    this.sim.destroy();
  }

  refitIngest(): void {
    fitIngest(this.refs.ingestStage);
  }

  /** Separate loop: the sim self-gates on cluster visibility. */
  private simTick = (t: number) => {
    this.simRaf = requestAnimationFrame(this.simTick);
    const root = this.refs.root;
    if (!root) return;
    if (!this.sim.ensureInit(root)) return;
    this.sim.step(window.innerHeight, t);
  };

  private tick = () => {
    this.raf = requestAnimationFrame(this.tick);
    const root = this.refs.root;
    if (!root) return;
    const now = Date.now();

    if (!this.M || now - this.measuredAt > MEASURE_MS) {
      this.measuredAt = now;
      const r = measure(
        {
          root,
          ingestScene: this.refs.ingestScene,
          plantCanvas: this.refs.plantCanvas,
          actCanvas: this.refs.actCanvas,
          ambientCanvas: this.refs.ambientCanvas,
        },
        this.vp,
      );
      this.M = r.M;
      this.docH = r.docH;
    }

    const M = this.M;
    const vh = window.innerHeight;
    const rawSy = window.scrollY;
    const inten = Number(this.hooks.getParallax() ?? 1);

    // ── double-lerp scroll smoothing: raw → scroll pass (0.05) → media pass (0.08)
    if (this.sySmooth === undefined) {
      this.sySmooth = rawSy;
      this.syMedia = rawSy;
    }
    const jumping =
      (this.jumpUntil && now < this.jumpUntil) || Math.abs(rawSy - this.sySmooth) > vh * 3;
    if (jumping) {
      this.sySmooth = rawSy;
      this.syMedia = rawSy;
      // release the bypass once the programmatic scroll has settled
      if (this.jumpUntil && Math.abs(rawSy - this.lastJumpSy) < 0.5 && now - this.jumpSettle > 120) {
        this.jumpUntil = 0;
      }
      if (Math.abs(rawSy - this.lastJumpSy) >= 0.5) this.jumpSettle = now;
      this.lastJumpSy = rawSy;
    } else {
      this.sySmooth += (rawSy - this.sySmooth) * 0.05;
      this.syMedia += (this.sySmooth - this.syMedia) * 0.08;
    }
    const sy = this.sySmooth;
    const syM = this.syMedia;

    if (this.refs.heroContent && rawSy < vh * 1.4) {
      put(this.refs.heroContent, 'transform', 'translateY(' + (syM * -0.3).toFixed(1) + 'px)');
      this.parallaxY = syM * 0.1;
    }

    if (rawSy < vh * 1.6) {
      M.cards.forEach((card) => {
        const baseRot = parseFloat(card.dataset.baseRot || '0');
        const dur = parseFloat(card.dataset.floatDur || '5000');
        const delay = parseFloat(card.dataset.floatDelay || '0');
        const floatY = Math.sin(((now - delay) / dur) * Math.PI * 2) * -8;
        put(
          card, 'transform',
          'perspective(1000px) translateY(' + (floatY + syM * -0.3).toFixed(1) + 'px) rotateX(' +
            (-this.mouse.y * 5).toFixed(2) + 'deg) rotateY(' +
            (this.mouse.x * 5).toFixed(2) + 'deg) rotateZ(' + baseRot + 'deg)',
        );
      });
    }

    M.depths.forEach((d) => {
      const depth = d.d * inten;
      let offset: number;
      if (d.pinned) {
        // the frame is pinned, so the text isn't moving: the dots must not
        // either, only mouse drift
        offset = 0;
      } else {
        const top = d.o.top - rawSy;
        if (top + d.o.h < -220 || top > vh + 220) return;
        offset = (d.o.top - syM + d.o.h / 2 - vh / 2) * depth;
      }
      put(
        d.el, 'translate',
        (this.mouse.x * -18 * depth).toFixed(1) + 'px ' +
          (offset + this.mouse.y * -12 * depth).toFixed(1) + 'px',
      );
    });

    M.tilts.forEach((t) => {
      const top = t.o.top - rawSy;
      if (top + t.o.h < 0 || top > vh) return;
      const cx = (t.o.left + t.o.w / 2) / window.innerWidth - 0.5;
      const cy = (t.o.top - syM + t.o.h / 2) / vh - 0.5;
      const amt = 3 * inten;
      put(
        t.el, 'transform',
        'perspective(1200px) rotateX(' + (cy * amt).toFixed(2) + 'deg) rotateY(' +
          (-cx * amt + this.mouse.x * 2).toFixed(2) + 'deg)',
      );
    });

    this.tickAct1(M, vh, rawSy, sy);
    this.tickAct2(M, vh, rawSy, sy);
    this.tickAct3(M, vh, rawSy, sy);
    this.tickNav(M, vh, rawSy, sy);

    if (this.refs.ambientCanvas) this.ambient.draw(this.refs.ambientCanvas, syM, vh, this.mouse);

    if (M.gal) {
      const gt = M.gal.top - rawSy;
      if (gt < vh + 200 && gt + M.gal.h > -200) this.marquee.update(now);
      else this.marquee.resetClock(now);
    }
    if (M.plant && this.refs.plantCanvas) {
      const ptop = M.plant.top - rawSy;
      if (ptop + M.plant.h > 0 && ptop < vh) this.plant.draw(this.refs.plantCanvas);
    }
  };

  private tickAct1(M: Measured, vh: number, rawSy: number, sy: number): void {
    const canvas = this.refs.actCanvas;
    const exploring = this.hooks.getExploring();
    const expOut = this.hooks.getExpOut();
    if ((exploring || expOut) && canvas) {
      drawExplore(canvas, this.graph, this.view, this.hooks.getExpNode());
    }
    if (!M.act1 || exploring || expOut || !canvas) return;
    const top = M.act1.o.top - rawSy;
    if (top + M.act1.o.h <= -100 || top >= vh + 100) return;

    const p = clamp01(-(M.act1.o.top - sy) / Math.max(1, M.act1.o.h - vh));
    drawScroll(canvas, this.graph, this.view, p);

    M.caps.forEach((c) => {
      const wn = ACT1_WINDOWS[c.i];
      const fadeIn = smooth((p - wn[0]) / 0.05);
      const fadeOut = 1 - smooth((p - (wn[1] - 0.04)) / 0.05);
      // the last caption stays up rather than fading out
      const o = c.i === 3 ? clamp01(fadeIn) : clamp01(Math.min(fadeIn, fadeOut));
      put(c.el, 'opacity', o.toFixed(2));
      put(
        c.el, 'transform',
        (c.i === 3 ? '' : 'translateY(-50%) ') + 'translateY(' + ((1 - o) * 22).toFixed(1) + 'px)',
      );
    });
    M.ticks.forEach((t) => {
      const wn = ACT1_WINDOWS[t.i];
      const active = p >= wn[0] && p < (wn[1] === 1.01 ? 2 : wn[1] + 0.02);
      put(t.el, 'background', active ? '#8FD9A8' : 'rgba(230,242,232,0.2)');
      put(t.el, 'height', active ? '38px' : '26px');
    });
  }

  private tickAct2(M: Measured, vh: number, rawSy: number, sy: number): void {
    if (!M.act2 || !M.scene) return;
    const top = M.act2.o.top - rawSy;
    if (top + M.act2.o.h <= -100 || top >= vh + 100) return;

    const p = clamp01(-(M.act2.o.top - sy) / Math.max(1, M.act2.o.h - vh));
    const sc = M.scene;
    if (!sc.doc || sc.tiles.length !== 4 || !sc.docL || !sc.tileL) return;

    const counts = [0, 0, 0, 0];
    sc.chips.forEach((ch) => {
      const t0 = 0.06 + ch.i * 0.058;
      const t1 = t0 + 0.24;
      const f = clamp01((p - t0) / (t1 - t0));
      if (f <= 0) {
        put(ch.el, 'opacity', '0');
        if (ch.docLine) put(ch.docLine, 'opacity', '1');
        return;
      }
      // dim the source line once its chip has lifted off
      if (ch.docLine) put(ch.docLine, 'opacity', f > 0.15 ? '0.22' : '1');
      if (f >= 1) {
        put(ch.el, 'opacity', '0');
        counts[ch.dest]++;
        return;
      }
      const e = smooth(f);
      const dl = sc.docL;
      const tl = sc.tileL[ch.dest];
      const fx = dl.x + 24;
      const fy = dl.y + 58 + ch.line * 17;
      const tx = tl.x + 18;
      const ty = tl.y + tl.h - 44;
      // quadratic Bézier arcing 150px above the higher endpoint
      const mx2 = (fx + tx) / 2;
      const my2 = Math.min(fy, ty) - 150;
      const u = 1 - e;
      const x = u * u * fx + 2 * u * e * mx2 + e * e * tx;
      const y = u * u * fy + 2 * u * e * my2 + e * e * ty;
      put(ch.el, 'opacity', String(Math.min(1, f * 10, (1 - f) * 8 + 0.15)));
      put(
        ch.el, 'transform',
        'translate(' + x.toFixed(1) + 'px,' + y.toFixed(1) + 'px) scale(' + (1 - e * 0.2).toFixed(2) + ')',
      );
    });

    counts.forEach((c, i) => {
      const el = sc.counts[i];
      if (el && el.textContent !== '+' + c) el.textContent = '+' + c;
      if (c > this.tileCounts[i]) {
        const tile = sc.tiles[i] as HTMLElement & { __shadow?: string };
        if (tile.__shadow === undefined) tile.__shadow = tile.style.boxShadow || '';
        tile.style.transform = 'scale(1.045)';
        tile.style.boxShadow = '0 18px 44px rgba(12,86,56,0.18)';
        setTimeout(() => {
          tile.style.transform = 'scale(1)';
          tile.style.boxShadow = tile.__shadow as string;
        }, 200);
      }
      this.tileCounts[i] = c;
    });
  }

  private tickAct3(M: Measured, vh: number, rawSy: number, sy: number): void {
    const carousel = this.refs.carousel;
    if (!M.act3 || !carousel) return;
    const top = M.act3.o.top - rawSy;
    if (top + M.act3.o.h <= -100 || top >= vh + 100) return;

    const p = clamp01(-(M.act3.o.top - sy) / Math.max(1, M.act3.o.h - vh));
    const docked = p > 0.86;
    let target: number;
    let ease = 0.09;
    if (docked) {
      // shortest way round, and a gentler glide than the scroll-driven spin
      const want = -120 * this.hooks.getTutorMode();
      target = want + 360 * Math.round((this.rotCur - want) / 360);
      ease = 0.028;
    } else {
      const k = clamp01((p - 0.06) / 0.72) * 2;
      const seg = Math.floor(Math.min(k, 1.999));
      const f = k - seg;
      const e = smooth((f - 0.3) / 0.4);
      target = -(seg + e) * 120;
      const facing = Math.round(-target / 120) % 3;
      if (facing !== this.tutorFacing) {
        this.tutorFacing = facing;
        this.hooks.setTutorMode(facing);
      }
    }
    this.rotCur += (target - this.rotCur) * ease;
    put(carousel, 'transform', 'rotateY(' + this.rotCur.toFixed(2) + 'deg)');

    const facingNow = ((Math.round(-this.rotCur / 120) % 3) + 3) % 3;
    M.tcaps.forEach((c) => {
      put(c.el, 'transition', 'opacity 400ms ease');
      put(c.el, 'opacity', c.i === (docked ? this.hooks.getTutorMode() : facingNow) ? '1' : '0');
    });
    M.panels.forEach((pn) => {
      const ang = (((pn.i * 120 + this.rotCur) % 360) + 360) % 360;
      put(pn.el, 'opacity', (0.3 + 0.7 * Math.max(0, Math.cos((ang * Math.PI) / 180))).toFixed(2));
    });
    if (M.pills) {
      put(M.pills, 'opacity', docked ? '1' : '0');
      put(M.pills, 'pointerEvents', docked ? 'auto' : 'none');
    }
  }

  private tickNav(M: Measured, vh: number, rawSy: number, sy: number): void {
    if (M.stem) put(M.stem, 'width', (clamp01(sy / this.docH) * 100).toFixed(2) + '%');

    const past = sy > vh * 0.7;
    const dy = rawSy - this.jumpLastY;
    if (Math.abs(dy) > 1.5) {
      this.jumpLastY = rawSy;
      if (dy > 0) {
        this.jumpSeen = performance.now();
        if (!this.hooks.getJumpDown()) this.hooks.setJumpDown(true);
      } else if (this.hooks.getJumpDown() && !this.hooks.getJumpOpen()) {
        this.hooks.setJumpDown(false);
      }
    } else if (
      this.hooks.getJumpDown() &&
      !this.hooks.getJumpOpen() &&
      performance.now() - this.jumpSeen > 1600
    ) {
      this.hooks.setJumpDown(false);
    }

    // recolour the jump pill when it sits over the dark act
    if (M.dark && M.jumpPill) {
      const mid = rawSy + vh * 0.9;
      const onDark = mid > M.dark.top && mid < M.dark.top + M.dark.h;
      if (onDark !== this.jumpOnDark) {
        this.jumpOnDark = onDark;
        if (M.jumpLabel) {
          put(M.jumpLabel, 'color', onDark ? '#B9D9C4' : '#61726A');
          put(
            M.jumpLabel, 'text-shadow',
            onDark ? '0 1px 10px rgba(4,18,12,0.85)' : '0 0 8px rgba(246,248,244,0.9)',
          );
        }
        M.jumpTicks.forEach((t) => put(t, 'opacity', onDark ? '0.9' : '1'));
      }
    }

    if (past !== this.hooks.getPastHero()) this.hooks.setPastHero(past);

    let activeIdx = 0;
    M.nav.forEach((n, i) => {
      if (i > 0 && n.top - sy < vh * 0.5) activeIdx = i;
    });
    if (activeIdx !== this.activeNav) {
      this.activeNav = activeIdx;
      M.nav.forEach((n, i) => {
        if (n.dot) {
          put(
            n.dot, 'background',
            i < activeIdx ? '#4FA574' : i === activeIdx ? '#0E9E5A' : 'rgba(18,32,26,0.18)',
          );
          put(n.dot, 'box-shadow', i === activeIdx ? '0 0 0 3px rgba(14,158,90,0.18)' : 'none');
        }
        put(n.btn, 'color', i === activeIdx ? '#0C5638' : '#61726A');
        put(n.btn, 'background', i === activeIdx ? 'rgba(12,86,56,0.07)' : 'transparent');
      });
      M.jumpTicks.forEach((t, i) => {
        put(
          t, 'background',
          i === activeIdx
            ? '#0E9E5A'
            : i < activeIdx
              ? 'rgba(79,165,116,0.6)'
              : this.jumpOnDark
                ? 'rgba(230,242,232,0.28)'
                : 'rgba(18,32,26,0.18)',
        );
        put(t, 'transform', i === activeIdx ? 'scale(1.5)' : 'scale(1)');
      });
      const cur = M.nav[activeIdx];
      if (M.jumpLabel && cur) M.jumpLabel.textContent = cur.label;
    }
  }
}
