'use client';

import { useEffect, useState, useRef, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { useUser } from '@/context/UserContext';
import { useScrollLock } from '@/lib/useScrollLock';
import { Network, Sparkles, FilePlus2, Brain, CalendarClock, Users, PenSquare } from 'lucide-react';
import HowItWorks from '@/components/HowItWorks';
import SignInModal from '@/components/SignInModal';
import { BRAND_FOREST } from '@/lib/brand';
import { Button } from "@/components/ui";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:5000';

const SCRAMBLE_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!<>-_\\/[]{}=+*^?#_";

// Hand-tuned atmospheric orb palettes, hardcoded because they feed canvas
// fillStyle where CSS var() doesn't resolve. #3e6f8a mirrors --info in
// globals.css — the muted blue chosen to de-neon the old #3B82F6 (#106).
const CLUSTER_COLORS = ['#9CA3AF', '#D97706', '#3e6f8a', '#8A63D2', '#14B8A6', '#EF4444'];
const CLUSTER_SEEDS_BG = [10.0, 11.3, 12.6, 13.9, 15.2, 16.5];
const CLUSTER_INIT_POS = [
  { ox: -222, oy: -29, oz:  15 },
  { ox: -161, oy: -59, oz: -20 },
  { ox:  -81, oy: -42, oz:  30 },
  { ox:  -67, oy:  17, oz:   0 },
  { ox: -168, oy:  59, oz:  20 },
  { ox: -229, oy:   8, oz: -30 },
];

/* The globals.css `prefers-reduced-motion` block only neutralizes CSS
   animations and transitions. The hero's canvas and card RAF loops are JS and
   have to opt out themselves, or a reduced-motion visitor keeps paying for a
   60fps render they asked not to see. */
const REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)';

export default function LandingPage() {
  const router = useRouter();
  const { userReady, isAuthenticated } = useUser();

  const [heroMounted, setHeroMounted] = useState(false);
  const [heroText1, setHeroText1] = useState('');
  const [heroText2, setHeroText2] = useState('');
  const [signInOpen, setSignInOpen] = useState(false);
  const [signInError, setSignInError] = useState<string | null>(null);
  const [betaModalOpen, setBetaModalOpen] = useState(false);
  const [betaModalClosing, setBetaModalClosing] = useState(false);
  const [betaEmail, setBetaEmail] = useState('');
  const [betaEmailError, setBetaEmailError] = useState('');
  const [betaSubmitted, setBetaSubmitted] = useState(false);
  const [betaEverSubmitted, setBetaEverSubmitted] = useState(false);
  const [betaSubmitting, setBetaSubmitting] = useState(false);
  const closeModal = useCallback(() => {
    setBetaModalClosing(true);
    setTimeout(() => {
      setBetaModalOpen(false);
      setBetaModalClosing(false);
      setBetaSubmitted(false);
      setBetaEmail('');
      setBetaEmailError('');
    }, 200);
  }, []);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const heroContentRef = useRef<HTMLDivElement>(null);
  const floatingCardsRef = useRef<HTMLDivElement>(null);
  const navRef = useRef<HTMLElement>(null);
  const ambientGlowRef = useRef<HTMLDivElement>(null);
  const parallaxYRef = useRef(0);
  const mouseRef = useRef({ x: 0, y: 0 });

  useEffect(() => {
    if (betaSubmitted) {
      const t = setTimeout(() => closeModal(), 3200);
      return () => clearTimeout(t);
    }
  }, [betaSubmitted, closeModal]);
  // Pre-auth there is no app shell, so <body> is the real scroll container and
  // useScrollLock resolves to it.
  useScrollLock(betaModalOpen);

  // Always start at the top of the landing page so Hero → Features → HowItWorks
  // Step 1 → 2 → 3 plays in order. Without this, browser scroll restoration on
  // reload / hot reload can drop the user mid-section where Step 2 is showing.
  useEffect(() => {
    if (typeof window !== 'undefined' && 'scrollRestoration' in window.history) {
      window.history.scrollRestoration = 'manual';
    }
    window.scrollTo({ top: 0, behavior: 'instant' });
  }, []);

  // If we landed here from an auth callback error or middleware redirect,
  // surface the message in the sign-in modal and clean the param from the URL.
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const params = new URLSearchParams(window.location.search);
    const err = params.get('error');
    if (!err) return;
    setSignInError(err);
    setSignInOpen(true);
    params.delete('error');
    const qs = params.toString();
    const next = window.location.pathname + (qs ? `?${qs}` : '');
    window.history.replaceState({}, '', next);
  }, []);

  const scrambleText = useCallback((setter: (v: string) => void, final: string, duration: number) => {
    const start = Date.now();
    const interval = setInterval(() => {
      const progress = (Date.now() - start) / duration;
      if (progress >= 1) { setter(final); clearInterval(interval); return; }
      setter(final.split('').map((ch, idx) => {
        if (ch === ' ' || ch === '\n') return ch;
        if (progress > idx / final.length) return ch;
        return SCRAMBLE_CHARS[Math.floor(Math.random() * SCRAMBLE_CHARS.length)];
      }).join(''));
    }, 30);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    const timeout = setTimeout(() => {
      setHeroMounted(true);
      scrambleText(setHeroText1, 'Sapling', 1000);
      setTimeout(() => scrambleText(setHeroText2, 'Grow Your Knowledge', 1200), 200);
    }, 300);
    return () => clearTimeout(timeout);
  }, [scrambleText]);

  // 3D Canvas graph
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d', { alpha: true });
    if (!ctx) return;

    let width = 0, height = 0;
    let rotAngle = 0;
    let animId = 0;

    const reduceMotion = window.matchMedia(REDUCED_MOTION_QUERY);
    let animating = !reduceMotion.matches;

    // #3e6f8a mirrors --info (globals.css); literal because canvas can't resolve var().
    const palette = [
      { c: '#8A63D2', w: 0.24 }, { c: '#3e6f8a', w: 0.24 },
      { c: '#D97706', w: 0.20 }, { c: '#14B8A6', w: 0.15 },
      { c: '#9CA3AF', w: 0.10 }, { c: '#D1D5DB', w: 0.07 },
    ];
    function randColor() {
      let r = Math.random(), s = 0;
      for (const p of palette) { s += p.w; if (r <= s) return p.c; }
      return palette[0].c;
    }

    const clusters = [
      { x: -600, y: -250, z: 80 },  { x: -350, y: -100, z: -120 },
      { x: -100, y: -300, z: 200 }, { x: 150, y: -150, z: -80 },
      { x: 400, y: -250, z: 150 },  { x: 600, y: -100, z: -50 },
      { x: -500, y: 100, z: -150 }, { x: -200, y: 200, z: 100 },
      { x: 50, y: 150, z: -200 },   { x: 300, y: 250, z: 120 },
      { x: 550, y: 150, z: -100 },  { x: -400, y: 350, z: 60 },
      { x: 0, y: 0, z: 0 },         { x: 200, y: -50, z: -150 },
    ];
    const spread = 280;
    const bgNodes = Array.from({ length: 220 }, () => {
      const cl = clusters[Math.floor(Math.random() * clusters.length)];
      return {
        ox: cl.x + (Math.random() - 0.5) * spread,
        oy: cl.y + (Math.random() - 0.5) * spread,
        oz: cl.z + (Math.random() - 0.5) * spread,
        color: randColor(),
        radius: 1 + Math.random() * 4,
        seed: Math.random() * 100,
        clusterIndex: undefined as number | undefined,
      };
    });
    const clusterNodes = CLUSTER_INIT_POS.map((pos, i) => ({
      ox: pos.ox, oy: pos.oy, oz: pos.oz,
      color: CLUSTER_COLORS[i],
      radius: 2.5 + Math.random() * 1.5,
      seed: CLUSTER_SEEDS_BG[i],
      clusterIndex: i as number | undefined,
    }));
    const nodes = [...bgNodes, ...clusterNodes];

    function resize() {
      width = window.innerWidth;
      height = window.innerHeight;
      canvas!.width = width * devicePixelRatio;
      canvas!.height = height * devicePixelRatio;
      ctx!.scale(devicePixelRatio, devicePixelRatio);
      // Resizing clears the backing store. With the loop parked there's no
      // next frame to repaint it, so repaint the static one here.
      if (!animating) draw();
    }
    window.addEventListener('resize', resize);
    resize();

    function draw() {
      if (!ctx) return;
      ctx.clearRect(0, 0, width, height);
      rotAngle += 0.0008;
      const fl = 1000, cx = width / 2, cy = height / 2, t = Date.now() * 0.001;
      const mx = mouseRef.current.x, my = mouseRef.current.y;

      const proj = nodes.map(n => {
        const ny = n.oy + Math.sin(t * 0.4 + n.seed) * 15;
        let x = n.ox * Math.cos(rotAngle) - n.oz * Math.sin(rotAngle);
        let z = n.oz * Math.cos(rotAngle) + n.ox * Math.sin(rotAngle);
        x -= mx * (z + fl) * 0.02;
        const y2 = ny - my * (z + fl) * 0.02;
        const sc = fl / (fl + z);
        return { x: x * sc + cx, y: y2 * sc + cy - parallaxYRef.current, z, sc, n };
      }).sort((a, b) => b.z - a.z);

      ctx.globalCompositeOperation = 'source-over';
      ctx.lineWidth = 0.5;
      for (let i = 0; i < proj.length; i++) {
        for (let j = i + 1; j < proj.length; j++) {
          const p1 = proj[i], p2 = proj[j];
          const d = Math.hypot(p1.x - p2.x, p1.y - p2.y);
          if (d < 70 * p1.sc) {
            const a = (1 - d / (70 * p1.sc)) * 0.15 * Math.min(1, p1.sc);
            if (a > 0.002) {
              ctx.strokeStyle = `rgba(156,163,175,${a})`;
              ctx.beginPath(); ctx.moveTo(p1.x, p1.y); ctx.lineTo(p2.x, p2.y); ctx.stroke();
            }
          }
        }
      }

      proj.forEach(p => {
        if (p.z > -fl) {
          const breathe = 0.92 + 0.08 * Math.sin(t * 0.6 + p.n.seed);
          const fogA = p.z > 500 ? Math.max(0, 1 - (p.z - 500) / 500) : 1;
          const r = p.n.radius * p.sc * breathe;
          if (r > 0.1) {
            ctx.globalAlpha = fogA;
            ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, Math.PI * 2); ctx.fillStyle = p.n.color; ctx.fill();
          }
        }
      });
      ctx.globalAlpha = 1;

      if (animating) animId = requestAnimationFrame(draw);
    }

    // Toggling the OS preference mid-session either parks the loop on a
    // static frame or restarts it; `draw` self-schedules only when animating.
    const onMotionPrefChange = () => {
      const next = !reduceMotion.matches;
      if (next === animating) return;
      animating = next;
      cancelAnimationFrame(animId);
      draw();
    };
    reduceMotion.addEventListener('change', onMotionPrefChange);

    draw();
    return () => {
      window.removeEventListener('resize', resize);
      reduceMotion.removeEventListener('change', onMotionPrefChange);
      cancelAnimationFrame(animId);
    };
  }, []);

  // Mouse + scroll
  useEffect(() => {
    const onMouse = (e: MouseEvent) => {
      mouseRef.current = { x: (e.clientX / window.innerWidth - 0.5) * 2, y: (e.clientY / window.innerHeight - 0.5) * 2 };
    };
    let lastSy = window.scrollY;

    const updateNavChrome = (sy: number) => {
      const nav = navRef.current;
      if (!nav) return;
      const scrollingDown = sy > lastSy;
      const pastHero = sy > window.innerHeight * 0.5;
      nav.style.transform = scrollingDown && pastHero ? 'translateY(-100%)' : 'translateY(0)';
      nav.classList.remove('shadow-sm');
      nav.style.background = 'transparent';
      nav.style.backdropFilter = 'none';
      nav.style.setProperty('-webkit-backdrop-filter', 'none');
      nav.style.borderBottomColor = 'transparent';
    };

    const updateAmbientGlow = (sy: number) => {
      const glow = ambientGlowRef.current;
      if (!glow) return;
      const progress = Math.min(1, Math.max(0, (sy - 20) / 260));
      const eased = progress * progress;
      glow.style.opacity = eased.toString();
    };

    const onScroll = () => {
      const sy = window.scrollY;
      if (heroContentRef.current && sy < window.innerHeight) {
        heroContentRef.current.style.transform = `translateY(${sy * -0.3}px)`;
        parallaxYRef.current = sy * 0.1;
      }
      updateNavChrome(sy);
      updateAmbientGlow(sy);
      lastSy = sy;
    };

    document.addEventListener('mousemove', onMouse);
    window.addEventListener('scroll', onScroll);
    onScroll();
    return () => { document.removeEventListener('mousemove', onMouse); window.removeEventListener('scroll', onScroll); };
  }, []);

  // Floating cards parallax
  useEffect(() => {
    // The cards are static markup, so resolve the NodeList and parse their
    // dataset floats once instead of re-doing both 60 times a second.
    const cards = Array.from(
      floatingCardsRef.current?.querySelectorAll<HTMLElement>('.floating-card') ?? [],
    ).map(el => ({
      el,
      baseRot: parseFloat(el.dataset.baseRot || '0'),
      dur: parseFloat(el.dataset.floatDur || '5000'),
      delay: parseFloat(el.dataset.floatDelay || '0'),
    }));
    if (cards.length === 0) return;

    const reduceMotion = window.matchMedia(REDUCED_MOTION_QUERY);
    let animId = 0;
    let animating = !reduceMotion.matches;

    function paint() {
      const t = Date.now();
      const mx = mouseRef.current.x, my = mouseRef.current.y;
      // Reduced motion keeps the cards' resting tilt but drops the drift,
      // the mouse tilt and the scroll parallax.
      const rx = animating ? -my * 5 : 0;
      const ry = animating ? mx * 5 : 0;
      const par = animating ? window.scrollY * -0.3 : 0;
      for (const { el, baseRot, dur, delay } of cards) {
        const floatY = animating ? Math.sin((t - delay) / dur * Math.PI * 2) * -8 : 0;
        el.style.transform = `perspective(1000px) translateY(${floatY + par}px) rotateX(${rx}deg) rotateY(${ry}deg) rotateZ(${baseRot}deg)`;
      }
      if (animating) animId = requestAnimationFrame(paint);
    }

    const onMotionPrefChange = () => {
      const next = !reduceMotion.matches;
      if (next === animating) return;
      animating = next;
      cancelAnimationFrame(animId);
      paint();
    };
    reduceMotion.addEventListener('change', onMotionPrefChange);

    paint();
    return () => {
      reduceMotion.removeEventListener('change', onMotionPrefChange);
      cancelAnimationFrame(animId);
    };
  }, []);

  // Intersection observer for fade-ups
  useEffect(() => {
    const obs = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.remove('opacity-0', 'translate-y-[30px]');
          if (entry.target.classList.contains('landing-stat-fade-up')) startCounters(entry.target as HTMLElement);
          obs.unobserve(entry.target);
        }
      });
    }, { threshold: 0.2 });
    document.querySelectorAll('.landing-fade-up, .landing-stat-fade-up').forEach(el => {
      el.classList.add('opacity-0', 'translate-y-[30px]', 'transition-all', 'duration-700', 'ease-out');
      obs.observe(el);
    });
    return () => obs.disconnect();
  }, []);

  // Spotlight card mouse-follow
  useEffect(() => {
    const cards = Array.from(document.querySelectorAll<HTMLElement>('.landing-spotlight-card'));
    if (cards.length === 0) return;

    // `getBoundingClientRect` per mousemove forces a layout flush on every
    // pointer sample. Measure on enter instead and hold the rect until
    // something can actually have moved the card.
    const rects = new WeakMap<HTMLElement, DOMRect>();

    const measure = (card: HTMLElement) => {
      const r = card.getBoundingClientRect();
      rects.set(card, r);
      return r;
    };
    const onEnter = (e: Event) => { measure(e.currentTarget as HTMLElement); };
    const onMove = (e: MouseEvent) => {
      const card = e.currentTarget as HTMLElement;
      const r = rects.get(card) ?? measure(card);
      card.style.setProperty('--mouse-x', `${e.clientX - r.left}px`);
      card.style.setProperty('--mouse-y', `${e.clientY - r.top}px`);
    };
    // Rects are viewport-relative, so scrolling invalidates them even though
    // the card hasn't moved in the document. Drop them and re-measure lazily.
    const invalidate = () => { for (const c of cards) rects.delete(c); };

    cards.forEach(c => {
      c.addEventListener('mouseenter', onEnter);
      c.addEventListener('mousemove', onMove);
    });
    window.addEventListener('scroll', invalidate, { passive: true });
    window.addEventListener('resize', invalidate);
    return () => {
      cards.forEach(c => {
        c.removeEventListener('mouseenter', onEnter);
        c.removeEventListener('mousemove', onMove);
      });
      window.removeEventListener('scroll', invalidate);
      window.removeEventListener('resize', invalidate);
    };
  }, []);

  function startCounters(container: HTMLElement) {
    container.querySelectorAll<HTMLElement>('.counter, .counter-float').forEach(el => {
      if (el.classList.contains('counted')) return;
      el.classList.add('counted');
      const target = parseFloat(el.dataset.target || '0');
      const isFloat = el.classList.contains('counter-float');
      const dur = 1500, startT = performance.now();
      function update(now: number) {
        const p = Math.min((now - startT) / dur, 1);
        const ease = 1 - Math.pow(1 - p, 4);
        el.textContent = isFloat ? (target * ease).toFixed(1) : Math.floor(target * ease).toLocaleString();
        if (p < 1) requestAnimationFrame(update);
        else el.textContent = isFloat ? target.toFixed(1) : target.toLocaleString();
      }
      requestAnimationFrame(update);
    });
  }

  // ── Onboarding entry ──────────────────────────────────────────────
  // The signup flow lives at /onboarding (screens/Onboarding). Unauthenticated
  // visitors sign in first; SignInModal routes them onward based on
  // onboarding_completed.
  function startOnboarding() {
    if (!userReady) return;
    if (!isAuthenticated) {
      setSignInError(null);
      setSignInOpen(true);
      return;
    }
    router.push('/onboarding');
  }

  return (
    <div className="landing-page antialiased" style={{ fontFamily: "var(--font-inter), sans-serif", color: 'var(--text, #1a1a1a)', background: 'transparent' }}>
      <div ref={ambientGlowRef} className="landing-ambient-glow" />

      {/* ═══ Initial load intro overlay ═══ */}
      <div
        className="landing-intro-overlay"
        style={{
          opacity: heroMounted ? 0 : 1,
          pointerEvents: heroMounted ? 'none' as const : 'auto' as const,
        }}
      >
        <div className="landing-intro-orbit">
          <div className="landing-intro-orbit-ring">
            <div className="landing-intro-orbit-node landing-intro-orbit-node--green" />
            <div className="landing-intro-orbit-node landing-intro-orbit-node--amber" />
            <div className="landing-intro-orbit-node landing-intro-orbit-node--blue" />
            <div className="landing-intro-orbit-node landing-intro-orbit-node--purple" />
          </div>
          <div className="text-center">
            <div className="font-playfair text-3xl sm:text-4xl font-semibold text-[var(--brand-forest)]">
              Sapling
            </div>
            <div className="mt-2 text-xs sm:text-sm font-jetbrains tracking-[0.2em] uppercase text-[var(--text-dim)]">
              Growing your knowledge
            </div>
          </div>
        </div>
      </div>

      {/* ═══ Navbar ═══ */}
      <nav
        ref={navRef}
        className="fixed top-0 w-full z-50 border-b border-solid px-6 py-4"
        style={{
          background: 'rgba(255,255,255,0)',
          borderBottomColor: 'transparent',
          opacity: heroMounted ? 1 : 0,
          transform: heroMounted ? 'translateY(0)' : 'translateY(-30px)',
          transition: 'opacity 800ms cubic-bezier(0.22,1,0.36,1), transform 800ms cubic-bezier(0.22,1,0.36,1)',
        }}
      >
        <div className="max-w-[88%] mx-auto flex items-center justify-between w-full">
          <button type="button" aria-label="Sapling — scroll to top" className="flex items-center cursor-pointer group" style={{ gap: '4px' }} onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}>
            <img src="/sapling-icon.svg" alt="" style={{ width: '26px', height: '26px', flexShrink: 0, position: 'relative', top: '-2px' }} />
            <span style={{ fontFamily: "var(--font-spectral), 'Spectral', Georgia, serif", fontWeight: 700, fontSize: '20px', color: 'var(--brand-forest)', letterSpacing: '-0.02em', lineHeight: 1.1 }}>Sapling</span>
          </button>
          <div className="flex items-center">
            <button onClick={() => { setSignInError(null); setSignInOpen(true); }} className="text-[var(--text-dim)] hover:text-[var(--text)] font-medium text-sm tracking-wide transition-all duration-300 mr-6 hidden sm:block">Sign In</button>
            <Button variant="primary" size="lg" style={{ padding: '6px 14px' }} onClick={startOnboarding}>
              Get Started
            </Button>
          </div>
        </div>
      </nav>

      {/* ═══ Hero Section ═══ */}
      <section className="relative min-h-screen flex items-center justify-center">
        <div aria-hidden className="absolute inset-0 pointer-events-none z-0">
          <div className="sapling-mesh-blob sapling-mesh-blob--1" />
          <div className="sapling-mesh-blob sapling-mesh-blob--2" />
        </div>
        <canvas ref={canvasRef} className="absolute inset-0 z-0 w-full h-full pointer-events-auto opacity-100" />

        {/* Floating Glass Accent Cards */}
        <div ref={floatingCardsRef} className="absolute inset-0 z-10 hidden lg:block pointer-events-none">
          <div
            className="floating-card absolute w-52 liquid-glass rounded-2xl p-5"
            style={{ position: 'absolute', top: '24%', right: '12%', opacity: heroMounted ? 1 : 0, transition: 'opacity 0.6s ease 1.0s' }}
            data-base-rot="4" data-float-delay="1000" data-float-dur="6000"
          >
            <div className="flex flex-col gap-3">
              <div className="flex items-center gap-2"><div className="w-2 h-2 rounded-full bg-[var(--brand-forest)]" /><span className="text-xs text-[var(--text-dim)] uppercase tracking-wide">Mastered</span></div>
              <div className="flex items-center gap-2"><div className="w-2 h-2 rounded-full bg-[#D97706]" /><span className="text-xs text-[var(--text-dim)] uppercase tracking-wide">Learning</span></div>
              <div className="flex items-center gap-2"><div className="w-2 h-2 rounded-full bg-[#EF4444]" /><span className="text-xs text-[var(--text-dim)] uppercase tracking-wide">Struggling</span></div>
              <div className="flex items-center gap-2"><div className="w-2 h-2 rounded-full bg-[#9CA3AF]" /><span className="text-xs text-[var(--text-dim)] uppercase tracking-wide">Unexplored</span></div>
            </div>
          </div>

          <div
            className="floating-card absolute w-44 liquid-glass rounded-2xl p-4 flex flex-col gap-2"
            style={{ position: 'absolute', bottom: '34%', left: '14%', opacity: heroMounted ? 1 : 0, transition: 'opacity 0.6s ease 1.2s' }}
            data-base-rot="-6" data-float-delay="500" data-float-dur="4500"
          >
            <div className="liquid-glass-subtle rounded-xl py-2 flex items-center justify-center gap-2">
              <PenSquare className="text-[var(--text-dim)] w-4 h-4" strokeWidth={1.5} />
              <span className="text-xs text-[var(--text-dim)]">Quick Quiz</span>
            </div>
            <div className="liquid-glass-subtle rounded-xl py-2 flex items-center justify-center gap-2">
              <Users className="text-[var(--text-dim)] w-4 h-4" strokeWidth={1.5} />
              <span className="text-xs text-[var(--text-dim)]">Study Room</span>
            </div>
          </div>
        </div>

        {/* Hero Content */}
        <div ref={heroContentRef} className="relative z-20 flex flex-col items-center text-center max-w-4xl px-6">
          <h1 style={{
            opacity: heroMounted ? 1 : 0,
            transform: heroMounted ? 'translateY(0)' : 'translateY(25px)',
            transition: 'all 700ms cubic-bezier(0.22,1,0.36,1) 300ms',
          }} className="font-playfair text-5xl sm:text-7xl md:text-8xl lg:text-[10rem] font-semibold leading-[1.15] tracking-tight pb-8 px-4 text-[var(--brand-forest)]">
            <span>{heroText1 || '\u00A0'}</span>
          </h1>

          <p style={{
            opacity: heroMounted ? 1 : 0,
            transform: heroMounted ? 'translateY(0)' : 'translateY(25px)',
            transition: 'all 700ms cubic-bezier(0.22,1,0.36,1) 500ms',
          }} className="font-playfair text-2xl sm:text-3xl md:text-4xl text-[var(--text-dim)] max-w-xl mx-auto mt-2 leading-relaxed tracking-tight font-medium">
            {heroText2 || '\u00A0'}
          </p>

          <div style={{
            opacity: heroMounted ? 1 : 0,
            transform: heroMounted ? 'translateY(0)' : 'translateY(25px)',
            transition: 'all 700ms cubic-bezier(0.22,1,0.36,1) 700ms',
          }} className="flex flex-col items-center gap-4 mt-10">
            <div style={{ position: 'relative', display: 'inline-flex', flexDirection: 'column', alignItems: 'center', gap: 6 }}>
              <Button
                variant="primary"
                size="xl"
                onClick={() => { setBetaModalOpen(true); if (betaEverSubmitted) setBetaSubmitted(true); }}
              >
                Sign up for Beta Testing
              </Button>
            </div>
          </div>
        </div>

        {/* Scroll Indicator */}
        <div style={{ opacity: heroMounted ? 1 : 0, transition: 'opacity 1s ease 1.2s' }} className="absolute bottom-8 left-1/2 landing-animate-float-indicator flex flex-col items-center">
          <div className="w-px h-14 landing-divider-v" />
          <span className="font-jetbrains text-xs tracking-[0.4em] text-[var(--text-dim)] opacity-70 mt-3">SEE WHAT&apos;S INSIDE</span>
        </div>
      </section>

      {/* ═══ Features Section ═══ */}
      <div>
        <section id="features" className="landing-section relative py-32 md:py-40 z-10 overflow-hidden">
          <div aria-hidden className="absolute inset-0 pointer-events-none z-0">
            <div className="sapling-mesh-blob sapling-mesh-blob--3" style={{ top: '6%', left: '-10%', opacity: 0.32, width: '36vw', height: '36vw' }} />
            <div className="sapling-mesh-blob sapling-mesh-blob--2" style={{ bottom: '10%', right: '-12%', opacity: 0.20, width: '32vw', height: '32vw' }} />
          </div>
          <div className="absolute top-0 left-0 w-full h-px landing-divider" />

          <div className="max-w-7xl mx-auto px-6 lg:px-12 relative z-[1]">
            {/* Editorial heading: asymmetric split, breathing room. */}
            <div className="grid md:grid-cols-12 gap-8 md:gap-12 mb-20 md:mb-28 landing-fade-up">
              <div className="md:col-span-7">
                <span className="font-jetbrains text-[0.7rem] tracking-[0.32em] text-[var(--brand-forest)] uppercase font-medium">In the Sapling kit</span>
                <h2 className="font-playfair text-5xl md:text-7xl font-semibold text-[var(--text)] mt-5 leading-[1.02] tracking-tight">
                  Tools that bend to <em className="not-italic text-[var(--brand-forest)]">your study</em>, not the other way around.
                </h2>
              </div>
              <div className="md:col-span-4 md:col-start-9 md:pt-8 flex flex-col justify-end">
                <p className="font-inter text-[var(--text-dim)] text-base leading-relaxed font-light">
                  Six instruments, tuned to one another. Each is a verb you reach for; together they make a quiet system that learns you back.
                </p>
                <div className="mt-6 flex items-center gap-3">
                  <span className="block h-px w-12 bg-[var(--brand-forest)]" />
                  <span className="font-jetbrains text-[0.65rem] tracking-[0.3em] text-[var(--text-dim)] uppercase">Scroll the catalog</span>
                </div>
              </div>
            </div>

            {/* Editorial feature catalog: hairline rows, no boxes. */}
            <ol className="landing-feature-list border-t border-[var(--text-dim)]/15">
              {[
                { icon: Network,       title: 'Knowledge Graph',     desc: 'Every concept becomes a node in a living 3D network. Watch them glow as you master topics and see how everything connects.' },
                { icon: Sparkles,      title: 'Adaptive Study Paths', desc: 'The AI reads your knowledge gaps and lays out the optimal sequence — so you always study the right thing at the right time.' },
                { icon: FilePlus2,     title: 'Universal Upload',     desc: 'Drop in syllabi, textbooks, or notes. Sapling extracts every concept and maps it onto your graph automatically.' },
                { icon: Brain,         title: 'Adaptive Quizzes',     desc: 'Questions that re-tune to your level in real time. They press where you are strong and meet you where you struggle.' },
                { icon: CalendarClock, title: 'Spaced Repetition',    desc: 'Scientifically-timed reviews move concepts from short-term to long-term memory. Sapling handles the scheduling.' },
                { icon: Users,         title: 'Live Study Rooms',     desc: 'Join classmates in shared rooms. Compare knowledge maps. Learn together, in real time, on the same canvas.' },
              ].map((feature, i) => (
                <li
                  key={feature.title}
                  className="landing-feature-row group relative border-b border-[var(--text-dim)]/15 landing-fade-up"
                  style={{ transitionDelay: `${i * 70}ms` }}
                >
                  <div className="grid md:grid-cols-12 items-center gap-6 md:gap-8 py-9 md:py-12 px-2 md:px-4 transition-colors duration-500">
                    {/* Index marker. */}
                    <div className="md:col-span-1 font-jetbrains text-[0.7rem] tracking-[0.3em] text-[var(--text-dim)] transition-colors duration-500 group-hover:text-[var(--brand-forest)]">
                      <span className="inline-block tabular-nums">0{i + 1}</span>
                      <span className="hidden md:inline-block ml-3 align-middle h-px w-6 bg-[var(--text-dim)]/30 group-hover:bg-[var(--brand-forest)]/60 transition-colors duration-500" />
                    </div>

                    {/* Title with bare inline icon — no circle, no color. */}
                    <div className="md:col-span-5 flex items-center gap-4 md:gap-5 min-w-0">
                      <feature.icon
                        aria-hidden
                        className="landing-feature-icon shrink-0 w-5 h-5 md:w-6 md:h-6 text-[var(--text)] transition-transform duration-700 ease-out group-hover:scale-110 group-hover:-rotate-6"
                        strokeWidth={1.5}
                      />
                      <h3 className="landing-feature-title font-playfair text-2xl md:text-3xl lg:text-4xl font-semibold text-[var(--text)] tracking-tight leading-[1.05]">
                        {feature.title}
                      </h3>
                    </div>

                    {/* Description: shifted left, generous width for body copy. */}
                    <div className="md:col-span-6">
                      <p className="font-inter text-[var(--text-dim)] text-[0.95rem] leading-relaxed font-light max-w-[52ch]">
                        {feature.desc}
                      </p>
                    </div>
                  </div>

                  {/* Hover-driven underline sweep, brand green. */}
                  <span
                    aria-hidden
                    className="landing-feature-underline pointer-events-none absolute left-0 bottom-0 h-[2px] w-0 bg-[var(--brand-forest)] group-hover:w-full transition-[width] duration-[900ms] ease-out"
                  />
                </li>
              ))}
            </ol>

            {/* Tail mark: editorial closing rule. */}
            <div className="mt-10 flex items-center gap-4 landing-fade-up">
              <span className="block h-px flex-1 bg-[var(--text-dim)]/15" />
              <span className="font-jetbrains text-[0.65rem] tracking-[0.32em] text-[var(--text-dim)] uppercase">— end of catalog</span>
            </div>
          </div>
        </section>

        <HowItWorks />

        {/* ═══ Final CTA ═══ */}
        <section className="landing-section py-32 relative text-center z-10">
          {/* Blend from HowItWorks' dark-green tint down to the mesh */}
          <div
            aria-hidden
            className="pointer-events-none absolute left-0 right-0 z-0"
            style={{
              top: 0,
              height: 'clamp(240px, 42vh, 480px)',
              background: 'linear-gradient(to bottom, rgba(20,83,45,0.08) 0%, rgba(20,83,45,0.04) 45%, rgba(20,83,45,0) 100%)',
            }}
          />
          <div aria-hidden className="absolute inset-0 pointer-events-none z-0">
            <div className="sapling-mesh-blob sapling-mesh-blob--1" style={{ top: '0%', right: '-15%', left: 'auto', opacity: 0.38, width: '38vw', height: '38vw' }} />
            <div className="sapling-mesh-blob sapling-mesh-blob--2" style={{ bottom: '0%', left: '-12%', opacity: 0.28, width: '32vw', height: '32vw' }} />
          </div>
          <div className="relative z-10 max-w-3xl mx-auto px-6 landing-fade-up">
            <h2 className="font-playfair text-5xl md:text-7xl font-semibold text-[var(--text)] tracking-tight leading-[1.05]">
              Ready to <br /> Start <span className="text-[var(--brand-forest)] pr-2">Growing?</span>
            </h2>
            <p className="text-[var(--text-dim)] text-lg mt-6 font-light">Join students who learn smarter, not harder.</p>
            <div className="mt-10 flex flex-col items-center">
              <Button variant="primary" size="xl" onClick={startOnboarding}>
                Get Started
              </Button>
            </div>
          </div>
        </section>

        {/* ═══ Footer ═══ */}
        <footer className="landing-section border-t border-white/35 py-12 px-8 relative z-10">
          <div className="max-w-7xl mx-auto flex flex-col md:flex-row items-center justify-between gap-6">
            <div className="flex items-center gap-2">
              <img src="/sapling-icon.svg" alt="Sapling" style={{ width: '20px', height: '20px' }} />
              <span className="text-sm font-light tracking-wide text-[var(--text-dim)]">Sapling · © 2026</span>
            </div>
            <div className="flex flex-wrap justify-center gap-6">
              <a href="/about" className="text-[var(--text-dim)] hover:text-[var(--text)] text-sm transition-colors">About</a>
              <a href="/careers" className="text-[var(--text-dim)] hover:text-[var(--text)] text-sm transition-colors">Careers</a>
              <a href="/terms" className="text-[var(--text-dim)] hover:text-[var(--text)] text-sm transition-colors">Terms of Service</a>
              <a href="/privacy" className="text-[var(--text-dim)] hover:text-[var(--text)] text-sm transition-colors">Privacy Policy</a>
            </div>
          </div>
          <div className="max-w-7xl mx-auto mt-8 pt-6 border-t border-white/25 text-center">
            <p className="text-xs text-[var(--text-dim)] opacity-75 font-light tracking-wide">
              © 2026 Andres Lopez, Jack He, Luke Cooper, and Jose Gael Cruz-Lopez. All Rights Reserved.
            </p>
          </div>
        </footer>
      </div>

      {/* ═══ Beta / Newsletter Panel ═══ */}
      {betaModalOpen && betaSubmitted && (
        <div
          className={`fixed inset-0 z-[100] flex items-center justify-center p-4 ${betaModalClosing ? 'modal-backdrop-out' : 'modal-backdrop-in'}`}
          style={{ background: 'rgba(12,18,26,0.45)' }}
          onClick={closeModal}
        >
          <div
            className={`${betaModalClosing ? 'modal-card-out' : 'modal-card-in'}`}
            style={{
              background: 'linear-gradient(145deg, #d5e8d8 0%, #e8f0e3 45%, #f0ebe0 100%)',
              borderRadius: 20,
              padding: '40px 52px',
              textAlign: 'center',
              border: '1px solid rgba(255,255,255,0.7)',
              boxShadow: '0 20px 60px rgba(15,23,42,0.15)',
            }}
            onClick={e => e.stopPropagation()}
          >
            <h2 style={{ margin: 0, fontFamily: "var(--font-playfair), 'Playfair Display', Georgia, serif", fontSize: 32, lineHeight: 1.1, fontWeight: 600, letterSpacing: '-0.02em', color: '#1a1a1a' }}>
              You&apos;re on the <span style={{ fontStyle: 'italic', color: 'var(--brand-forest)' }}>tree.</span>
            </h2>
            <p style={{ margin: '10px 0 0', fontSize: 17, color: '#4b5563', fontStyle: 'italic' }}>
              See you in the inbox - The Team
            </p>
          </div>
        </div>
      )}
      {betaModalOpen && !betaSubmitted && (
        <div
          className={`fixed inset-0 z-[100] flex items-center justify-center p-4 ${betaModalClosing ? 'modal-backdrop-out' : 'modal-backdrop-in'}`}
          style={{ background: 'rgba(12,18,26,0.65)' }}
          onClick={() => { if (!betaSubmitting) closeModal(); }}
        >
          <div
            className={`relative w-full ${betaModalClosing ? 'modal-card-out' : 'modal-card-in'}`}
            style={{
              maxWidth: 'min(1040px, 94vw)',
              width: '100%',
              background: 'linear-gradient(145deg, #d5e8d8 0%, #e8f0e3 45%, #f0ebe0 100%)',
              borderRadius: 24,
              display: 'grid',
              gridTemplateColumns: '1fr 1px 1fr',
              minHeight: 560,
              maxHeight: 'calc(100vh - 48px)',
              overflow: 'hidden',
              border: '1px solid rgba(255,255,255,0.7)',
              boxShadow: '0 20px 60px rgba(15,23,42,0.12), inset 0 0 0 1px rgba(255,255,255,0.5)',
            }}
            onClick={e => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-label="Beta access and newsletter signup"
          >
            {/* Close */}
            <button
              onClick={closeModal}
              aria-label="Close dialog"
              style={{
                position: 'absolute', top: 18, right: 18, zIndex: 10,
                width: 32, height: 32, borderRadius: 16,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                color: '#4b5563', fontSize: 20, lineHeight: 1,
                background: 'none', border: 'none', cursor: 'pointer',
                transition: 'background 0.15s',
              }}
              onMouseEnter={e => (e.currentTarget.style.background = 'rgba(107,114,128,0.1)')}
              onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
            >×</button>

            {/* ── Left: brand + perks panel ── */}
            <div style={{
              padding: '36px 36px 32px',
              background: 'linear-gradient(145deg, #d5e8d8 0%, #e8f0e3 45%, #f0ebe0 100%)',
              display: 'flex', flexDirection: 'column', gap: 22,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <img src="/sapling-icon.svg" alt="Sapling" style={{ width: 22, height: 22 }} />
                <span style={{ fontFamily: "var(--font-spectral), 'Spectral', Georgia, serif", fontWeight: 700, fontSize: 17, color: 'var(--brand-forest)', letterSpacing: '-0.02em' }}>Sapling</span>
              </div>
              <div>
                <div style={{ fontFamily: "var(--font-jetbrains), 'JetBrains Mono', monospace", fontSize: 10.5, color: '#6b7280', letterSpacing: '0.22em', marginBottom: 14, textTransform: 'uppercase', fontWeight: 600 }}>Early access</div>
                <h2 style={{ margin: 0, fontFamily: "var(--font-playfair), 'Playfair Display', Georgia, serif", fontSize: 44, lineHeight: 1.05, fontWeight: 700, color: '#1a1a1a', letterSpacing: '-0.02em' }}>
                  Learn early.<br /><span style={{ fontStyle: 'italic', fontWeight: 800, color: 'var(--brand-forest)', fontFamily: "var(--font-playfair), 'Playfair Display', Georgia, serif" }}>Grow</span> with us.
                </h2>
                <p style={{ margin: '14px 0 0', fontSize: 13.5, lineHeight: 1.55, color: '#4b5563', maxWidth: 360 }}>
                  Sapling is being built alongside the students who&apos;ll use it most. Join early and help shape what it becomes.
                </p>
              </div>
              <div style={{ height: '1px', flexShrink: 0, background: 'rgba(107,114,128,0.15)' }} />
              <div>
                <h3 style={{ margin: '0 0 12px', fontFamily: "var(--font-playfair), 'Playfair Display', Georgia, serif", fontSize: 22, fontWeight: 700, color: '#1a1a1a', letterSpacing: '-0.02em' }}>
                  Beta Tester Role
                </h3>
                <div className="rounded-xl px-4 py-3 flex items-center gap-3" style={{ background: '#EBE6DC', border: '1px solid #D6D1C6' }}>
                  <div className="w-11 h-11 rounded-full flex items-center justify-center flex-shrink-0" style={{ background: '#374151', fontSize: '13px', fontWeight: 700, color: '#fff', fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif", letterSpacing: '0.02em' }}>
                    AK
                  </div>
                  <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span style={{ fontSize: '14px', fontWeight: 700, color: '#111827', fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif" }}>Alex Kim</span>
                      <span className="font-jetbrains" style={{
                        display: 'inline-flex', alignItems: 'center',
                        padding: '3px 10px', borderRadius: '9999px',
                        fontSize: '10px', fontWeight: 500,
                        letterSpacing: '0.1em', textTransform: 'uppercase',
                        background: 'rgba(212,175,55,0.08)', color: '#C9A227',
                        border: '1.5px solid rgba(212,175,55,0.55)',
                      }}>
                        Beta Tester
                      </span>
                    </div>
                    <span style={{ fontSize: '11px', color: '#9CA3AF', fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif" }}>@alexkim</span>
                  </div>
                </div>
                <p style={{ margin: '10px 2px 0', fontSize: 12.5, color: '#6b7280', lineHeight: 1.5, fontStyle: 'italic' }}>
                  The first mark on your profile. A permanent record of showing up early.
                </p>
              </div>
            </div>

            {/* ── Column divider ── */}
            <div style={{ background: 'rgba(107,114,128,0.15)', alignSelf: 'stretch' }} />

            {/* ── Right: newsletter form ── */}
            <div style={{ padding: '44px 42px 36px', display: 'flex', flexDirection: 'column', background: 'linear-gradient(145deg, #d5e8d8 0%, #e8f0e3 45%, #f0ebe0 100%)' }}>
              <div style={{ fontFamily: "var(--font-jetbrains), 'JetBrains Mono', monospace", fontSize: 10, color: '#D97706', letterSpacing: '0.3em', textTransform: 'uppercase', fontWeight: 500, marginBottom: 10 }}>
                ● Issue 001 dropping soon
              </div>
              <h1 style={{ margin: 0, fontFamily: "var(--font-playfair), 'Playfair Display', Georgia, serif", fontSize: 48, lineHeight: 1.05, fontWeight: 600, letterSpacing: '-0.025em', color: '#1a1a1a' }}>
                Join the<br />
                <span style={{ fontStyle: 'italic', fontWeight: 800, color: 'var(--brand-forest)', fontFamily: "var(--font-playfair), 'Playfair Display', Georgia, serif" }}>Newsletter</span>
              </h1>
              <p style={{ margin: '14px 0 0', fontSize: 15, color: '#4b5563', lineHeight: 1.5 }}>
                Hear fun stories from students like you.
              </p>
              <div style={{ marginTop: 28, display: 'flex', flexDirection: 'column', gap: 16 }}>
                {([
                  { dot: BRAND_FOREST, title: 'New features, first.', body: 'Every study mode, knowledge tool, and capability before anyone else sees it.' },
                  { dot: '#D97706', title: 'Real notes from the team.', body: "What we're figuring out as we build. Honest, occasional, and worth opening." },
                  { dot: '#8A63D2', title: 'Your input shapes what we build.', body: 'Early polls, roadmap previews, and a direct line to the people building it.' },
                ] as Array<{ dot: string; title: string; body: string }>).map(({ dot, title, body }) => (
                  <div key={title} style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: 12, alignItems: 'start' }}>
                    <div style={{ width: 8, height: 8, borderRadius: '50%', background: dot, boxShadow: `0 0 8px ${dot}55`, marginTop: 8, flexShrink: 0 }} />
                    <div>
                      <div style={{ fontSize: 14.5, fontWeight: 600, color: '#1a1a1a', marginBottom: 2, letterSpacing: '-0.005em' }}>{title}</div>
                      <div style={{ fontSize: 12.5, color: '#4b5563', lineHeight: 1.5 }}>{body}</div>
                    </div>
                  </div>
                ))}
              </div>
              <form
                onSubmit={async e => {
                  e.preventDefault();
                  const trimmed = betaEmail.trim();
                  if (!trimmed) { setBetaEmailError('Enter a valid email (e.g. you@example.com)'); return; }
                  const [local, domain] = trimmed.split('@');
                  if (!local || !domain || !domain.includes('.')) {
                    setBetaEmailError('Enter a valid email (e.g. you@example.com)');
                    return;
                  }
                  setBetaEmailError('');
                  setBetaSubmitting(true);
                  try {
                    await fetch(`${API_URL}/api/newsletter/subscribe`, {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ email: betaEmail.trim() }),
                    });
                  } catch {
                    // fail silently — still show success
                  }
                  setBetaSubmitting(false);
                  setBetaSubmitted(true);
                  setBetaEverSubmitted(true);
                }}
                style={{ marginTop: 'auto', paddingTop: 28 }}
              >
                <div style={{ position: 'relative', marginBottom: 10 }}>
                  <input
                    type="text"
                    aria-label="Email address"
                    placeholder="you@example.com"
                    value={betaEmail}
                    onChange={e => { setBetaEmail(e.target.value); setBetaEmailError(''); }}
                    style={{
                      width: '100%', padding: '14px 16px', fontSize: 14,
                      background: 'rgba(255,255,255,0.6)',
                      border: '1.5px solid rgba(107,114,128,0.25)',
                      borderRadius: 10,
                      transition: 'border-color 0.15s, box-shadow 0.15s',
                      fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif",
                      color: '#1a1a1a', boxSizing: 'border-box',
                    }}
                    onFocus={e => { e.target.style.borderColor = 'var(--brand-forest)'; e.target.style.boxShadow = '0 0 0 3px rgba(27,108,66,0.12)'; }}
                    onBlur={e => { e.target.style.borderColor = 'rgba(107,114,128,0.25)'; e.target.style.boxShadow = 'none'; }}
                  />
                  {betaEmailError && (
                    <p style={{ margin: '6px 0 0', fontSize: 11.5, color: '#dc2626', fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif" }}>
                      {betaEmailError}
                    </p>
                  )}
                </div>
                <button
                  type="submit"
                  disabled={betaSubmitting}
                  style={{
                    width: '100%', padding: '14px 16px', borderRadius: 10,
                    background: betaSubmitting ? '#4b5563' : 'var(--brand-forest)', color: '#fff',
                    fontSize: 14, fontWeight: 600, letterSpacing: '0.02em',
                    boxShadow: '0 8px 24px rgba(27,108,66,0.3)',
                    border: 'none', cursor: betaSubmitting ? 'default' : 'pointer',
                    transition: 'all 0.18s', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
                    fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif",
                  }}
                  onMouseEnter={e => { if (!betaSubmitting) e.currentTarget.style.background = 'var(--brand-forest-hover)'; }}
                  onMouseLeave={e => { if (!betaSubmitting) e.currentTarget.style.background = 'var(--brand-forest)'; }}
                >
                  {betaSubmitting ? 'Planting your node…' : <>Sign Me Up <span style={{ opacity: 0.7 }}>→</span></>}
                </button>
                <p style={{ margin: '12px 0 0', fontSize: 11.5, color: '#6b7280', textAlign: 'center', lineHeight: 1.5 }}>
                  By joining the newsletter, you&apos;ll also be added to the beta waitlist.
                </p>
              </form>
            </div>
          </div>
        </div>
      )}

      {/* ═══ Sign-in modal ═══ */}
      <SignInModal
        open={signInOpen}
        onClose={() => { setSignInOpen(false); setSignInError(null); }}
        errorCode={signInError}
      />
    </div>
  );
}
