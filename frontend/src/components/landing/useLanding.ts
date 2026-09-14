'use client';

/**
 * The bridge between React and the imperative landing engine.
 *
 * Ported from the `Component` class in `Sapling Landing v4.dc.html`. React
 * owns the discrete state (which card is open, which tutor mode, which FAQ);
 * the engine owns everything that changes per frame and writes it straight to
 * the DOM. The two meet here.
 *
 * State the engine needs to *read* is mirrored into refs, so the engine's
 * getters never close over a stale render.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { humanizeError } from '@/lib/errorMessage';
import { SCRAMBLE } from '@/lib/landing/content';
import { LandingEngine } from '@/lib/landing/engine';
import type { BuiltGraph } from '@/lib/landing/engine/graph';
import { armFlip, flipClose, flipOpen } from '@/lib/landing/engine/flip';
import {
  beginExitExplore, beginExplore, pickNode, settleExitExplore,
} from '@/lib/landing/engine/graphView';

/** How long the intro overlay holds before the hero takes over. */
const INTRO_MS = 1900;
/** Explore exit transition length, after which the camera hands back. */
const EXPLORE_OUT_MS = 720;
const SCRAMBLE_TICK_MS = 30;

/** One text slot scrambling into place during the intro cascade. */
export interface ScrambleStep {
  /** Which of the three hero text slots this step drives. */
  slot: 0 | 1 | 2;
  /** The string it settles on. */
  text: string;
  durationMs: number;
  /** Offset from the moment the hero mounts. Defaults to 0. */
  delayMs?: number;
}

/**
 * v5's cascade — the tagline leads and the wordmark follows 260ms behind.
 *
 * This is the reverse of v4's order, and both durations are shorter. The
 * v4 title screen it replaced has been deleted; the cascade stays a prop
 * so the sequence is stated at the call site rather than buried here.
 */
const DEFAULT_CASCADE: ScrambleStep[] = [
  { slot: 0, text: 'Grow Your Knowledge', durationMs: 760 },
  { slot: 1, text: 'Sapling', durationMs: 1000, delayMs: 260 },
];

export interface LandingProps {
  /** Parallax intensity, 0..2. */
  parallax?: number;
  fireflies?: boolean;
  /** Bypass the intro entirely (0ms delay). */
  skipIntro?: boolean;
  /** The intro scramble cascade. Defaults to v5's. */
  cascade?: ScrambleStep[];
  /** Run the `LOADING 000→100` counter behind the intro overlay. */
  loadCounter?: boolean;
}

export interface LandingRefs {
  root: React.RefObject<HTMLDivElement | null>;
  nav: React.RefObject<HTMLElement | null>;
  heroContent: React.RefObject<HTMLDivElement | null>;
  heroCanvas: React.RefObject<HTMLCanvasElement | null>;
  /** The WebGL canvas the v5 hero's three.js scene renders into. */
  glCanvas: React.RefObject<HTMLCanvasElement | null>;
  actCanvas: React.RefObject<HTMLCanvasElement | null>;
  ambientCanvas: React.RefObject<HTMLCanvasElement | null>;
  plantCanvas: React.RefObject<HTMLCanvasElement | null>;
  carousel: React.RefObject<HTMLDivElement | null>;
  ingestScene: React.RefObject<HTMLDivElement | null>;
  ingestStage: React.RefObject<HTMLDivElement | null>;
  cinema: React.RefObject<HTMLDivElement | null>;
  panel: React.RefObject<HTMLDivElement | null>;
  trackA: React.RefObject<HTMLDivElement | null>;
  trackB: React.RefObject<HTMLDivElement | null>;
}

export function useLanding(props: LandingProps) {
  const {
    parallax = 1, skipIntro = false,
    cascade = DEFAULT_CASCADE, loadCounter = false,
  } = props;

  // ── discrete state ────────────────────────────────────────────────────
  const [heroMounted, setHeroMounted] = useState(false);
  const [heroText0, setHeroText0] = useState('');
  const [heroText1, setHeroText1] = useState('');
  const [heroText2, setHeroText2] = useState('');
  /** Fake progress behind the intro overlay, 0..100. */
  const [loadPct, setLoadPct] = useState(0);
  /** True once the overlay has faded out and can leave the tree entirely. */
  const [introGone, setIntroGone] = useState(false);
  /**
   * The engine's graph, published once it exists.
   *
   * Must be the engine's own instance, not a second `buildGraph()` — the
   * builder seeds and shuffles with `Math.random`, so a separate call would
   * produce different node ordering and the explore HUD would describe a
   * different node than the one the canvas highlighted.
   */
  const [graph, setGraph] = useState<BuiltGraph | null>(null);
  const [tutorMode, setTutorMode] = useState(0);
  const [galIdx, setGalIdx] = useState(-1);
  const [modalAnim, setModalAnim] = useState(false);
  const [jumpOpen, setJumpOpen] = useState(false);
  const [pastHero, setPastHero] = useState(false);
  const [navMenuOpen, setNavMenuOpen] = useState(false);
  const [exploring, setExploring] = useState(false);
  const [expNode, setExpNode] = useState<number | null>(null);
  const [openFaq, setOpenFaq] = useState(0);
  const [email, setEmail] = useState('');
  const [subscribed, setSubscribed] = useState(false);
  /** In flight, so the form can disable rather than double-post. */
  const [subscribing, setSubscribing] = useState(false);
  /** Null unless the last attempt failed; shown next to the field. */
  const [subscribeError, setSubscribeError] = useState<string | null>(null);
  const [plantVal, setPlantVal] = useState('');
  const [plantedCount, setPlantedCount] = useState(0);
  const [jumpDown, setJumpDown] = useState(false);

  // Declared individually rather than as an object: React's refs lint rule
  // rejects `ref={obj.someRef}` in JSX, and flat refs read better at the call
  // site anyway. They are grouped into `refs` below purely for the engine.
  const rootRef = useRef<HTMLDivElement>(null);
  const navRef = useRef<HTMLElement>(null);
  const heroContentRef = useRef<HTMLDivElement>(null);
  const heroCanvasRef = useRef<HTMLCanvasElement>(null);
  const glCanvasRef = useRef<HTMLCanvasElement>(null);
  const actCanvasRef = useRef<HTMLCanvasElement>(null);
  const ambientCanvasRef = useRef<HTMLCanvasElement>(null);
  const plantCanvasRef = useRef<HTMLCanvasElement>(null);
  const carouselRef = useRef<HTMLDivElement>(null);
  const ingestSceneRef = useRef<HTMLDivElement>(null);
  const ingestStageRef = useRef<HTMLDivElement>(null);
  const cinemaRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const trackARef = useRef<HTMLDivElement>(null);
  const trackBRef = useRef<HTMLDivElement>(null);

  const refs: LandingRefs = {
    root: rootRef, nav: navRef, heroContent: heroContentRef, heroCanvas: heroCanvasRef,
    glCanvas: glCanvasRef,
    actCanvas: actCanvasRef, ambientCanvas: ambientCanvasRef, plantCanvas: plantCanvasRef,
    carousel: carouselRef, ingestScene: ingestSceneRef, ingestStage: ingestStageRef,
    cinema: cinemaRef, panel: panelRef, trackA: trackARef, trackB: trackBRef,
  };

  // ── mirrors, so the engine never reads a stale render ─────────────────
  const s = useRef({
    exploring, expNode, tutorMode, jumpOpen, pastHero, jumpDown, galIdx, parallax,
  });
  s.current = { exploring, expNode, tutorMode, jumpOpen, pastHero, jumpDown, galIdx, parallax };

  const expOut = useRef(false);
  const mqDragged = useRef(false);
  const flipRan = useRef(false);
  const engineRef = useRef<LandingEngine | null>(null);

  // ── engine lifecycle ──────────────────────────────────────────────────
  useEffect(() => {
    const engine = new LandingEngine(
      {
        get root() { return refs.root.current; },
        get nav() { return refs.nav.current; },
        get heroContent() { return refs.heroContent.current; },
        get actCanvas() { return refs.actCanvas.current; },
        get ambientCanvas() { return refs.ambientCanvas.current; },
        get plantCanvas() { return refs.plantCanvas.current; },
        get carousel() { return refs.carousel.current; },
        get ingestScene() { return refs.ingestScene.current; },
        get ingestStage() { return refs.ingestStage.current; },
      },
      {
        getExploring: () => s.current.exploring,
        getExpOut: () => expOut.current,
        getExpNode: () => s.current.expNode,
        getTutorMode: () => s.current.tutorMode,
        setTutorMode: (v) => setTutorMode(v),
        getJumpOpen: () => s.current.jumpOpen,
        getPastHero: () => s.current.pastHero,
        setPastHero: (v) => {
          setPastHero(v);
          if (!v) setJumpOpen(false);
        },
        getJumpDown: () => s.current.jumpDown,
        setJumpDown: (v) => setJumpDown(v),
        getParallax: () => s.current.parallax,
        onOpenGallery: (i, el) => openGal(i, el),
        setMarqueeDragged: (v) => { mqDragged.current = v; },
      },
    );
    engineRef.current = engine;
    setGraph(engine.graph);
    engine.plant.restore(refs.plantCanvas.current);
    setPlantedCount(engine.plant.labels.length);
    engine.start();
    engine.refitIngest();

    const onResize = () => engine.refitIngest();
    window.addEventListener('resize', onResize);
    return () => {
      window.removeEventListener('resize', onResize);
      engine.stop();
      engineRef.current = null;
      document.body.style.overflow = '';
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── hero canvas (own loop) ────────────────────────────────────────────
  useEffect(() => {
    const canvas = refs.heroCanvas.current;
    const engine = engineRef.current;
    if (!canvas || !engine) return;
    let stopped: { stop(): void } | null = null;
    // imported lazily so the module isn't pulled into the server bundle
    import('@/lib/landing/engine/hero').then(({ startHeroCanvas }) => {
      stopped = startHeroCanvas(canvas, () => engine.mouse, () => engine.parallaxY);
    });
    return () => stopped?.stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── hero WebGL panel rig (own loop) ───────────────────────────────────
  useEffect(() => {
    const canvas = refs.glCanvas.current;
    const engine = engineRef.current;
    if (!canvas || !engine) return;
    let rig: { stop(): void } | null = null;
    let cancelled = false;
    // three.js is heavy and browser-only; keep it out of the server bundle
    // and off the critical path
    import('@/lib/landing/hero3d').then(({ startHeroRig }) => {
      if (cancelled) return;
      rig = startHeroRig(canvas, () => engine.mouse, () => engine.heroShiftPx);
    });
    return () => {
      cancelled = true;
      rig?.stop();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── mouse, nav auto-hide, escape ──────────────────────────────────────
  useEffect(() => {
    const onMouse = (e: MouseEvent) => {
      const engine = engineRef.current;
      if (engine) {
        engine.mouse = {
          x: (e.clientX / window.innerWidth - 0.5) * 2,
          y: (e.clientY / window.innerHeight - 0.5) * 2,
        };
      }
    };
    document.addEventListener('mousemove', onMouse);

    let lastSy = window.scrollY;
    const onScroll = () => {
      const sy = window.scrollY;
      const nav = refs.nav.current;
      if (nav) {
        const down = sy > lastSy;
        const past = sy > window.innerHeight * 0.5;
        nav.style.transform = down && past ? 'translateY(-100%)' : 'translateY(0)';
      }
      lastSy = sy;
    };
    window.addEventListener('scroll', onScroll, { passive: true });

    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      if (s.current.galIdx >= 0) closeGal();
      else if (s.current.jumpOpen) setJumpOpen(false);
    };
    document.addEventListener('keydown', onKey);

    const onAway = (e: PointerEvent) => {
      const el = e.target as Element | null;
      if (s.current.jumpOpen && !el?.closest?.('.sapling-nav')) setJumpOpen(false);
      if (!el?.closest?.('.nav-panel, .nav-compact')) setNavMenuOpen(false);
    };
    document.addEventListener('pointerdown', onAway);

    return () => {
      document.removeEventListener('mousemove', onMouse);
      window.removeEventListener('scroll', onScroll);
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onAway);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── intro: overlay holds, then hero scrambles in ──────────────────────
  useEffect(() => {
    const timers: ReturnType<typeof setTimeout>[] = [];
    const intervals: ReturnType<typeof setInterval>[] = [];

    const scramble = (set: (v: string) => void, final: string, duration: number) => {
      const start = Date.now();
      const iv = setInterval(() => {
        const progress = (Date.now() - start) / duration;
        if (progress >= 1) {
          set(final);
          clearInterval(iv);
          return;
        }
        // characters lock in left-to-right as progress passes their index
        set(
          final
            .split('')
            .map((ch, idx) => {
              if (ch === ' ') return ch;
              if (progress > idx / final.length) return ch;
              return SCRAMBLE[Math.floor(Math.random() * SCRAMBLE.length)];
            })
            .join(''),
        );
      }, SCRAMBLE_TICK_MS);
      intervals.push(iv);
    };

    const setters = [setHeroText0, setHeroText1, setHeroText2];

    timers.push(
      setTimeout(() => {
        setHeroMounted(true);
        // the overlay fades over 700ms; drop it from the tree just after
        timers.push(setTimeout(() => setIntroGone(true), 900));
        cascade.forEach((step) => {
          const run = () => scramble(setters[step.slot], step.text, step.durationMs);
          if (step.delayMs) timers.push(setTimeout(run, step.delayMs));
          else run();
        });
      }, skipIntro ? 0 : INTRO_MS),
    );

    return () => {
      timers.forEach(clearTimeout);
      intervals.forEach(clearInterval);
    };
  }, [skipIntro, cascade]);

  // ── LOADING counter behind the overlay ────────────────────────────────
  // Ticks every 62ms in ragged +4..+12 jumps, exactly as the source does —
  // the unevenness is what makes it read as real work rather than a timer.
  useEffect(() => {
    if (!loadCounter) return;
    const iv = setInterval(() => {
      setLoadPct((p) => {
        if (p >= 100) { clearInterval(iv); return 100; }
        return Math.min(100, p + Math.ceil(Math.random() * 9) + 3);
      });
    }, 62);
    return () => clearInterval(iv);
  }, [loadCounter]);

  // Fade-ups used to live here as a `[data-reveal]` scan on a 900ms interval.
  // They are now the `FadeIn` component in `components/landing/anim`, which
  // declares the entrance where the block is written and shares one observer.
  // It also drops a flash the scan had: it set `opacity:0` in an effect after
  // paint, so a revealed block could show before hiding itself.

  // ── pause CSS animations in off-screen sections ───────────────────────
  // Set directly on the animated nodes: toggling a class on the section
  // forces a full subtree style recalc.
  useEffect(() => {
    if (!('IntersectionObserver' in window)) return;
    let io: IntersectionObserver | null = null;
    const t = setTimeout(() => {
      const root = refs.root.current;
      if (!root) return;
      io = new IntersectionObserver(
        (entries) => {
          entries.forEach((en) => {
            const list = (en.target as HTMLElement & { __animEls?: HTMLElement[] }).__animEls;
            if (!list) return;
            const st = en.isIntersecting ? '' : 'paused';
            for (let i = 0; i < list.length; i++) {
              if (list[i].style.animationPlayState !== st) list[i].style.animationPlayState = st;
            }
          });
        },
        { rootMargin: '15% 0px' },
      );
      root.querySelectorAll('section').forEach((sec) => {
        const els = Array.from(sec.querySelectorAll<HTMLElement>('*')).filter((el) => {
          const n = getComputedStyle(el).animationName;
          return n && n !== 'none';
        });
        if (!els.length) return;
        (sec as HTMLElement & { __animEls?: HTMLElement[] }).__animEls = els;
        io!.observe(sec);
      });
    }, 1200);
    return () => {
      clearTimeout(t);
      io?.disconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── explore mode ──────────────────────────────────────────────────────
  const enterExplore = useCallback(() => {
    const engine = engineRef.current;
    if (!engine || s.current.exploring) return;
    expOut.current = false;
    beginExplore(engine.view, engine.graph);
    document.body.style.overflow = 'hidden';
    const cinema = refs.cinema.current;
    if (cinema) {
      cinema.style.opacity = '0';
      cinema.style.pointerEvents = 'none';
    }
    setExploring(true);
    setExpNode(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const exitExplore = useCallback(() => {
    const engine = engineRef.current;
    if (!engine || !s.current.exploring || expOut.current) return;
    document.body.style.overflow = '';
    const cinema = refs.cinema.current;
    if (cinema) cinema.style.opacity = '';
    expOut.current = true;
    beginExitExplore(engine.view);
    setExploring(false);
    setExpNode(null);
    setTimeout(() => {
      expOut.current = false;
      settleExitExplore(engine.view);
    }, EXPLORE_OUT_MS);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── act canvas pointer handling (orbit, hover, pick) ──────────────────
  useEffect(() => {
    const canvas = refs.actCanvas.current;
    const engine = engineRef.current;
    if (!canvas || !engine) return;
    const view = engine.view;
    let dragging = false;
    let lastX = 0;
    let lastY = 0;
    let moved = 0;

    const onDown = (e: PointerEvent) => {
      dragging = true;
      moved = 0;
      lastX = e.clientX;
      lastY = e.clientY;
      canvas.style.cursor = 'grabbing';
      try { canvas.setPointerCapture(e.pointerId); } catch { /* not captureable */ }
    };
    const onMove = (e: PointerEvent) => {
      const r = canvas.getBoundingClientRect();
      view.actMouse = { x: e.clientX - r.left, y: e.clientY - r.top };
      if (s.current.exploring && !dragging) {
        const hit = pickNode(view, view.actMouse);
        const id = hit ? hit.i : null;
        if (id !== view.expHover) {
          view.expHover = id;
          canvas.style.cursor = id !== null ? 'pointer' : 'grab';
        }
      }
      if (!dragging) return;
      moved += Math.abs(e.clientX - lastX) + Math.abs(e.clientY - lastY);
      view.orbY += (e.clientX - lastX) * 0.005;
      view.orbX = Math.max(-0.5, Math.min(0.5, view.orbX + (e.clientY - lastY) * 0.003));
      lastX = e.clientX;
      lastY = e.clientY;
    };
    const onUp = (e: PointerEvent) => {
      dragging = false;
      canvas.style.cursor = 'grab';
      if (moved > 6) return;
      if (!s.current.exploring) { enterExplore(); return; }
      const r = canvas.getBoundingClientRect();
      const hit = pickNode(view, { x: e.clientX - r.left, y: e.clientY - r.top });
      setExpNode(hit ? hit.i : null);
    };
    const onLeave = () => { view.actMouse = null; view.expHover = null; };
    const onWheel = (e: WheelEvent) => {
      if (!s.current.exploring) return;
      e.preventDefault();
      view.expZoom = Math.max(0.3, Math.min(3, view.expZoom * (e.deltaY > 0 ? 0.92 : 1.08)));
    };

    canvas.addEventListener('pointerdown', onDown);
    canvas.addEventListener('pointermove', onMove);
    canvas.addEventListener('pointerup', onUp);
    canvas.addEventListener('pointerleave', onLeave);
    canvas.addEventListener('wheel', onWheel, { passive: false });
    return () => {
      canvas.removeEventListener('pointerdown', onDown);
      canvas.removeEventListener('pointermove', onMove);
      canvas.removeEventListener('pointerup', onUp);
      canvas.removeEventListener('pointerleave', onLeave);
      canvas.removeEventListener('wheel', onWheel);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enterExplore]);

  // ── marquee binding ───────────────────────────────────────────────────
  useEffect(() => {
    const engine = engineRef.current;
    if (!engine) return;
    if (refs.trackA.current) engine.marquee.bind(refs.trackA.current, 1);
    if (refs.trackB.current) engine.marquee.bind(refs.trackB.current, -1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── feature lab ───────────────────────────────────────────────────────
  const openGal = useCallback((i: number, from: HTMLElement | null) => {
    const engine = engineRef.current;
    if (!engine) return;
    document.body.style.overflow = 'hidden';
    armFlip(engine.flip, from);
    flipRan.current = false;
    setGalIdx(i);
    setModalAnim(true);
     
  }, []);

  const closeGal = useCallback(() => {
    const engine = engineRef.current;
    if (!engine) return;
    flipRan.current = false;
    setModalAnim(false);
    flipClose(engine.flip, refs.panel.current, () => {
      document.body.style.overflow = '';
      setGalIdx(-1);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** Runs the open FLIP once the overlay panel has actually mounted. */
  const registerPanel = useCallback((el: HTMLDivElement | null) => {
    refs.panel.current = el;
    const engine = engineRef.current;
    if (el && engine && !flipRan.current) {
      flipRan.current = true;
      flipOpen(engine.flip, el);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── newsletter / beta list ────────────────────────────────────────────
  /**
   * POSTs to the real endpoint and only reports success on a 2xx.
   *
   * The backend upserts on `email`, so signing up twice is a no-op there and
   * a second submit lands on the same success state rather than an error.
   */
  const subscribeNow = useCallback(async () => {
    const value = email.trim();
    if (!value.includes('@') || subscribing) return;
    setSubscribing(true);
    setSubscribeError(null);
    try {
      const { subscribeToNewsletter } = await import('@/lib/api');
      await subscribeToNewsletter(value);
      setSubscribed(true);
    } catch (err) {
      // `lib/api.ts` rejects with the raw response body, which is how
      // "Internal Server Error" ends up rendered at a user. humanizeError
      // keeps a server-supplied `detail` when there is one (a 422 on a bad
      // address is worth reading) and swaps anything else for the fallback.
      setSubscribeError(humanizeError(err, 'Could not sign you up just now. Please try again.'));
    } finally {
      setSubscribing(false);
    }
  }, [email, subscribing]);

  // ── navigation ────────────────────────────────────────────────────────
  const scrollToId = useCallback((id: string) => {
    const el = document.getElementById(id);
    if (!el) return;
    const y = el.getBoundingClientRect().top + window.scrollY - 40;
    engineRef.current?.markJump();
    window.scrollTo({ top: y, behavior: 'smooth' });
  }, []);

  const scrollTop = useCallback(() => {
    engineRef.current?.markJump();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }, []);

  // ── plant a concept ───────────────────────────────────────────────────
  const plant = useCallback(() => {
    const engine = engineRef.current;
    if (!engine) return;
    const n = engine.plant.plant(refs.plantCanvas.current, plantVal);
    if (n < 0) return;
    setPlantVal('');
    setPlantedCount(n);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plantVal]);

  return {
    rootRef, navRef, heroContentRef, heroCanvasRef, glCanvasRef, actCanvasRef, ambientCanvasRef,
    plantCanvasRef, carouselRef, ingestSceneRef, ingestStageRef, cinemaRef,
    trackARef, trackBRef,
    engineRef,
    state: {
      heroMounted, heroText0, heroText1, heroText2, loadPct, introGone, graph,
      tutorMode, galIdx, modalAnim, jumpOpen,
      pastHero, navMenuOpen, exploring, expNode, openFaq, email, subscribed,
      subscribing, subscribeError,
      plantVal, plantedCount, jumpDown,
    },
    set: {
      setTutorMode, setJumpOpen, setNavMenuOpen, setOpenFaq, setEmail,
      setSubscribed, setPlantVal, setExpNode,
    },
    actions: {
      enterExplore, exitExplore, openGal, closeGal, registerPanel,
      scrollToId, scrollTop, plant,
      subscribe: subscribeNow,
      resetSubscribeError: () => setSubscribeError(null),
    },
    mqDragged,
    expOut,
  };
}
