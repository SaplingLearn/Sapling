'use client';

import { useEffect, useState, useRef, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { useUser } from '@/context/UserContext';
import { Network, Sparkles, FilePlus2, Brain, CalendarClock, Users, PenSquare } from 'lucide-react';
import OnboardingFlow from '@/components/OnboardingFlow';
import HowItWorks from '@/components/HowItWorks';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:5000';

const SCRAMBLE_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!<>-_\\/[]{}=+*^?#_";

export default function LandingPage() {
  const router = useRouter();
  const { userReady, isAuthenticated } = useUser();

  const [heroMounted, setHeroMounted] = useState(false);
  const [heroText1, setHeroText1] = useState('');
  const [heroText2, setHeroText2] = useState('');
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [activeStep, setActiveStep] = useState(0);
  const [completed, setCompleted] = useState<Set<number>>(new Set());

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const heroContentRef = useRef<HTMLDivElement>(null);
  const floatingCardsRef = useRef<HTMLDivElement>(null);
  const navRef = useRef<HTMLElement>(null);
  const ambientGlowRef = useRef<HTMLDivElement>(null);
  const parallaxYRef = useRef(0);
  const mouseRef = useRef({ x: 0, y: 0 });

  useEffect(() => {
    if (userReady && isAuthenticated) {
      const pending = sessionStorage.getItem('sapling_onboarding_pending');
      if (pending) {
        sessionStorage.removeItem('sapling_onboarding_pending');
        setActiveStep(1);
        setCompleted(new Set([0]));
        setShowOnboarding(true);
      } else {
        router.replace('/dashboard');
      }
    }
  }, [userReady, isAuthenticated, router]);

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
    let animId: number;

    const palette = [
      { c: '#8A63D2', w: 0.25 }, { c: '#3B82F6', w: 0.25 },
      { c: '#D97706', w: 0.20 }, { c: '#14B8A6', w: 0.15 }, { c: '#D1D5DB', w: 0.15 },
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
    const nodes = Array.from({ length: 220 }, () => {
      const cl = clusters[Math.floor(Math.random() * clusters.length)];
      return {
        ox: cl.x + (Math.random() - 0.5) * spread,
        oy: cl.y + (Math.random() - 0.5) * spread,
        oz: cl.z + (Math.random() - 0.5) * spread,
        color: randColor(),
        radius: 1 + Math.random() * 4,
        seed: Math.random() * 100,
      };
    });

    function resize() {
      width = window.innerWidth;
      height = window.innerHeight;
      canvas!.width = width * devicePixelRatio;
      canvas!.height = height * devicePixelRatio;
      ctx!.scale(devicePixelRatio, devicePixelRatio);
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
            ctx.strokeStyle = `rgba(156,163,175,${a})`;
            ctx.beginPath(); ctx.moveTo(p1.x, p1.y); ctx.lineTo(p2.x, p2.y); ctx.stroke();
          }
        }
      }
      proj.forEach(p => {
        if (p.z > -fl) {
          const breathe = 0.92 + 0.08 * Math.sin(t * 0.6 + p.n.seed);
          const r = p.n.radius * p.sc * breathe;
          if (r > 0.1) {
            const fogA = p.z > 500 ? Math.max(0, 1 - (p.z - 500) / 500) : 1;
            ctx.globalAlpha = fogA;
            ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, Math.PI * 2); ctx.fillStyle = p.n.color; ctx.fill();
          }
        }
      });
      ctx.globalAlpha = 1;
      animId = requestAnimationFrame(draw);
    }
    draw();
    return () => { window.removeEventListener('resize', resize); cancelAnimationFrame(animId); };
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
    let animId: number;
    function tick() {
      const t = Date.now();
      const mx = mouseRef.current.x, my = mouseRef.current.y;
      floatingCardsRef.current?.querySelectorAll<HTMLElement>('.floating-card').forEach(card => {
        const baseRot = parseFloat(card.dataset.baseRot || '0');
        const dur = parseFloat(card.dataset.floatDur || '5000');
        const delay = parseFloat(card.dataset.floatDelay || '0');
        const floatY = Math.sin((t - delay) / dur * Math.PI * 2) * -8;
        const rx = -my * 5, ry = mx * 5;
        const par = window.scrollY * -0.3;
        card.style.transform = `perspective(1000px) translateY(${floatY + par}px) rotateX(${rx}deg) rotateY(${ry}deg) rotateZ(${baseRot}deg)`;
      });
      animId = requestAnimationFrame(tick);
    }
    tick();
    return () => cancelAnimationFrame(animId);
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
    const cards = document.querySelectorAll<HTMLElement>('.landing-spotlight-card');
    const handler = (e: MouseEvent) => {
      const card = (e.currentTarget as HTMLElement);
      const r = card.getBoundingClientRect();
      card.style.setProperty('--mouse-x', `${e.clientX - r.left}px`);
      card.style.setProperty('--mouse-y', `${e.clientY - r.top}px`);
    };
    cards.forEach(c => c.addEventListener('mousemove', handler));
    return () => cards.forEach(c => c.removeEventListener('mousemove', handler));
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

  if (userReady && isAuthenticated) return null;

  return (
    <div className="landing-page antialiased" style={{ fontFamily: "var(--font-inter), 'Inter', sans-serif", color: 'var(--brand-text1, #1a1a1a)', background: 'transparent' }}>
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
            <div className="font-playfair text-3xl sm:text-4xl font-semibold bg-gradient-to-r from-[#1B6C42] via-[#2D8F5C] to-[#1B6C42] bg-clip-text text-transparent">
              Sapling
            </div>
            <div className="mt-2 text-xs sm:text-sm font-jetbrains tracking-[0.2em] uppercase text-[var(--brand-text2)]">
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
          <div className="flex items-center cursor-pointer group" style={{ gap: '4px' }} onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}>
            <img src="/sapling-icon.svg" alt="Sapling" style={{ width: '26px', height: '26px', flexShrink: 0, position: 'relative', top: '-2px' }} />
            <span style={{ fontFamily: "var(--font-spectral), 'Spectral', Georgia, serif", fontWeight: 700, fontSize: '20px', color: '#1a5c2a', letterSpacing: '-0.02em', lineHeight: 1.1 }}>Sapling</span>
          </div>
          <div className="flex items-center">
            <button onClick={() => { window.location.href = `${API_URL}/api/auth/google`; }} className="text-[var(--brand-text2)] hover:text-[var(--brand-text1)] font-medium text-sm tracking-wide transition-all duration-300 mr-6 hidden sm:block">Sign In</button>
            <button onClick={() => setShowOnboarding(true)} className="relative overflow-hidden group bg-[#1B6C42] text-white px-7 py-2.5 rounded-full font-medium text-sm tracking-wide shadow-sm hover:shadow-md transition-all duration-400 hover:scale-[1.04] active:scale-[0.97] landing-btn-shimmer">
              Get Started
            </button>
          </div>
        </div>
      </nav>

      {/* ═══ Hero Section ═══ */}
      <section className="relative min-h-screen flex items-center justify-center">
        {/* Ambient orbs — scoped to hero */}
        <div aria-hidden className="absolute inset-0 pointer-events-none z-0">
          <div className="sapling-mesh-blob sapling-mesh-blob--1" />
          <div className="sapling-mesh-blob sapling-mesh-blob--2" />
        </div>
        <canvas ref={canvasRef} className="absolute inset-0 z-0 w-full h-full pointer-events-auto opacity-100" />

        {/* Floating Glass Accent Cards */}
        <div ref={floatingCardsRef} className="absolute inset-0 z-10 hidden lg:block pointer-events-none">
          <div
            className="floating-card absolute w-48 liquid-glass rounded-2xl p-4"
            style={{ position: 'absolute', top: '28%', left: '18%', opacity: heroMounted ? 1 : 0, transition: 'opacity 0.6s ease 0.8s' }}
            data-base-rot="-6" data-float-delay="0" data-float-dur="5000"
          >
            <span className="font-jetbrains text-xs text-[#3B82F6] font-medium block mb-3">CS 101</span>
            <div className="h-1 rounded-full bg-white/45 w-full overflow-hidden mb-2">
              <div className="h-full bg-[#3B82F6] w-[55%] rounded-full" />
            </div>
            <span className="text-xs text-[var(--brand-text2)] opacity-80 block">55% mastered</span>
          </div>

          {/* Card D: Progress summary under legend */}
          <div
            className="floating-card absolute w-52 liquid-glass rounded-2xl p-4"
            style={{ position: 'absolute', top: '52%', right: '18%', opacity: heroMounted ? 1 : 0, transition: 'opacity 0.6s ease 1.4s' }}
            data-base-rot="2" data-float-delay="1600" data-float-dur="5200"
          >
            <div className="flex flex-col gap-2 text-left">
              <div className="flex items-center justify-between text-xs text-[var(--brand-text2)]">
                <span>Total nodes</span>
                <span className="font-jetbrains text-[var(--brand-text1)]">2,413</span>
              </div>
              <div className="flex items-center justify-between text-xs text-[var(--brand-text2)]">
                <span>Mastered</span>
                <span className="font-jetbrains text-[#1B6C42]">68%</span>
              </div>
              <div className="flex items-center justify-between text-xs text-[var(--brand-text2)]">
                <span>On track</span>
                <span className="font-jetbrains text-[#D97706]">24%</span>
              </div>
            </div>
          </div>

          <div
            className="floating-card absolute w-52 liquid-glass rounded-2xl p-5"
            style={{ position: 'absolute', top: '24%', right: '18%', opacity: heroMounted ? 1 : 0, transition: 'opacity 0.6s ease 1.0s' }}
            data-base-rot="4" data-float-delay="1000" data-float-dur="6000"
          >
            <div className="flex flex-col gap-3">
              <div className="flex items-center gap-2"><div className="w-2 h-2 rounded-full bg-[#1B6C42]" /><span className="text-xs text-[var(--brand-text2)] uppercase tracking-wide">Mastered</span></div>
              <div className="flex items-center gap-2"><div className="w-2 h-2 rounded-full bg-[#D97706]" /><span className="text-xs text-[var(--brand-text2)] uppercase tracking-wide">Learning</span></div>
              <div className="flex items-center gap-2"><div className="w-2 h-2 rounded-full bg-[#EF4444]" /><span className="text-xs text-[var(--brand-text2)] uppercase tracking-wide">Struggling</span></div>
              <div className="flex items-center gap-2"><div className="w-2 h-2 rounded-full bg-[#9CA3AF]" /><span className="text-xs text-[var(--brand-text2)] uppercase tracking-wide">Unexplored</span></div>
            </div>
          </div>

          <div
            className="floating-card absolute w-44 liquid-glass rounded-2xl p-4 flex flex-col gap-2"
            style={{ position: 'absolute', bottom: '34%', left: '24%', opacity: heroMounted ? 1 : 0, transition: 'opacity 0.6s ease 1.2s' }}
            data-base-rot="-6" data-float-delay="500" data-float-dur="4500"
          >
            <div className="liquid-glass-subtle rounded-xl py-2 flex items-center justify-center gap-2">
              <PenSquare className="text-[var(--brand-text2)] w-4 h-4" strokeWidth={1.5} />
              <span className="text-xs text-[var(--brand-text2)]">Quick Quiz</span>
            </div>
            <div className="liquid-glass-subtle rounded-xl py-2 flex items-center justify-center gap-2">
              <Users className="text-[var(--brand-text2)] w-4 h-4" strokeWidth={1.5} />
              <span className="text-xs text-[var(--brand-text2)]">Study Room</span>
            </div>
          </div>
        </div>

        {/* Hero Content */}
        <div ref={heroContentRef} className="relative z-20 flex flex-col items-center text-center max-w-4xl px-6">
          <div style={{
            opacity: heroMounted ? 1 : 0,
            transform: heroMounted ? 'translateY(0)' : 'translateY(25px)',
            transition: 'all 700ms cubic-bezier(0.22,1,0.36,1) 100ms',
          }}>
            <div className="inline-flex items-center gap-2.5 liquid-glass-subtle rounded-full px-5 py-2">
              <div className="w-2 h-2 rounded-full bg-[#1B6C42] animate-pulse" />
              <span className="font-jetbrains text-xs tracking-[0.25em] uppercase text-[var(--brand-text2)] font-medium">AI-Powered Learning</span>
            </div>
          </div>

          <h1 style={{
            opacity: heroMounted ? 1 : 0,
            transform: heroMounted ? 'translateY(0)' : 'translateY(25px)',
            transition: 'all 700ms cubic-bezier(0.22,1,0.36,1) 300ms',
          }} className="font-playfair text-5xl sm:text-7xl md:text-8xl lg:text-[10rem] font-semibold leading-[1.15] tracking-tight mt-8 pb-8 px-4 bg-gradient-to-r from-[#1B6C42] via-[#2D8F5C] to-[#1B6C42] bg-clip-text text-transparent landing-animate-gradient">
            <span>{heroText1 || '\u00A0'}</span>
          </h1>

          <p style={{
            opacity: heroMounted ? 1 : 0,
            transform: heroMounted ? 'translateY(0)' : 'translateY(25px)',
            transition: 'all 700ms cubic-bezier(0.22,1,0.36,1) 500ms',
          }} className="font-playfair text-2xl sm:text-3xl md:text-4xl text-[var(--brand-text2)] max-w-xl mx-auto mt-7 leading-relaxed tracking-tight font-medium">
            {heroText2 || '\u00A0'}
          </p>

          <div style={{
            opacity: heroMounted ? 1 : 0,
            transform: heroMounted ? 'translateY(0)' : 'translateY(25px)',
            transition: 'all 700ms cubic-bezier(0.22,1,0.36,1) 700ms',
          }} className="flex flex-col sm:flex-row gap-4 mt-10 items-center justify-center">
            <button onClick={() => setShowOnboarding(true)} className="relative overflow-hidden group bg-[#1B6C42] text-white px-10 py-4 rounded-full font-medium text-base tracking-wide shadow-md hover:shadow-lg hover:bg-[#155A35] transition-all duration-500 hover:scale-[1.03] active:scale-[0.98] landing-btn-shimmer">
              Get Started
            </button>
            <button onClick={() => document.getElementById('features')?.scrollIntoView({ behavior: 'smooth' })} className="liquid-glass-subtle text-[var(--brand-text2)] hover:text-[var(--brand-text1)] px-10 py-4 rounded-full font-medium text-base transition-all duration-500 hover:scale-[1.02] active:scale-[0.98]">
              See What&apos;s Inside <span className="ml-1 opacity-50">↓</span>
            </button>
          </div>
        </div>

        {/* Scroll Indicator */}
        <div style={{ opacity: heroMounted ? 1 : 0, transition: 'opacity 1s ease 1.2s' }} className="absolute bottom-8 left-1/2 landing-animate-float-indicator flex flex-col items-center">
          <div className="w-px h-14 landing-divider-v" />
          <span className="font-jetbrains text-xs tracking-[0.4em] text-[var(--brand-text2)] opacity-70 mt-3">SCROLL</span>
        </div>
      </section>

      {/* ═══ Features Section ═══ */}
      <section id="features" className="landing-section relative py-32 z-10">
        <div aria-hidden className="absolute inset-0 pointer-events-none z-0">
          <div className="sapling-mesh-blob sapling-mesh-blob--3" style={{ top: '10%', left: '-8%', opacity: 0.28, width: '30vw', height: '30vw' }} />
        </div>
        <div className="absolute top-0 left-0 w-full h-px landing-divider" />
        <div className="max-w-6xl mx-auto px-6 lg:px-8 relative z-[1]">
          <div className="text-center mb-16 landing-fade-up">
            <span className="font-jetbrains text-xs tracking-[0.3em] text-[#1B6C42] uppercase font-medium">Features</span>
            <h2 className="font-playfair text-4xl md:text-6xl font-semibold text-[var(--brand-text1)] mt-4 leading-tight tracking-tight">
              Everything You Need<br />to Learn Smarter
            </h2>
            <p className="font-inter text-[var(--brand-text2)] text-lg mt-6 max-w-lg mx-auto font-light leading-relaxed">
              Six powerful tools. One beautiful platform. Built for how your brain actually works.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {[
              { icon: Network, color: '#1B6C42', bg: 'bg-[#1B6C42]/10', title: 'Interactive Knowledge Graph', desc: 'Every concept becomes a node in a living 3D network. Watch them glow green as you master topics and see how everything connects.' },
              { icon: Sparkles, color: '#D97706', bg: 'bg-[#D97706]/10', title: 'AI-Powered Study Paths', desc: 'Our AI analyzes your knowledge gaps and builds the optimal sequence so you always study the right thing at the right time.' },
              { icon: FilePlus2, color: '#14B8A6', bg: 'bg-[#14B8A6]/10', title: 'Upload Any Coursework', desc: 'Drop in syllabi, textbooks, or notes. Sapling extracts every concept and maps it to your knowledge graph automatically.' },
              { icon: Brain, color: '#EF4444', bg: 'bg-[#EF4444]/10', title: 'Adaptive Quizzes', desc: 'Questions that adapt to your level in real-time. They get harder as you improve and meet you where you are when you struggle.' },
              { icon: CalendarClock, color: '#1B6C42', bg: 'bg-[#1B6C42]/10', title: 'Spaced Repetition', desc: 'Scientifically-timed reviews move concepts from short-term to long-term memory. Sapling handles the scheduling.' },
              { icon: Users, color: '#3B82F6', bg: 'bg-[#3B82F6]/10', title: 'Study Rooms', desc: 'Join live study rooms with classmates. Compare knowledge maps. Learn together in real-time.' },
            ].map((feature, i) => (
              <div
                key={feature.title}
                className={`landing-spotlight-card landing-card-float-${i + 1} group liquid-glass rounded-2xl p-8 transition-[border-color,box-shadow] duration-500 hover:shadow-[0_12px_40px_rgba(0,0,0,0.06)] landing-fade-up`}
                style={{ transitionDelay: `${i * 80}ms` }}
              >
                <div className="relative z-10">
                  <div className={`landing-icon-container w-12 h-12 rounded-xl flex items-center justify-center mb-5 ${feature.bg}`}>
                    <feature.icon style={{ color: feature.color }} className="w-6 h-6" strokeWidth={1.5} />
                  </div>
                  <h3 className="text-[var(--brand-text1)] font-medium text-lg mb-3 tracking-tight">{feature.title}</h3>
                  <p className="text-[var(--brand-text2)] text-sm leading-relaxed font-light">{feature.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ═══ How It Works ═══ */}
      <HowItWorks />


      {/* ═══ Final CTA ═══ */}
      <section className="landing-section py-32 relative text-center z-10">
        <div aria-hidden className="absolute inset-0 pointer-events-none z-0">
          <div className="sapling-mesh-blob sapling-mesh-blob--1" style={{ top: '0%', right: '-15%', left: 'auto', opacity: 0.38, width: '38vw', height: '38vw' }} />
          <div className="sapling-mesh-blob sapling-mesh-blob--2" style={{ bottom: '0%', left: '-12%', opacity: 0.28, width: '32vw', height: '32vw' }} />
        </div>
        <div className="relative z-10 max-w-3xl mx-auto px-6 landing-fade-up">
          <h2 className="font-playfair text-5xl md:text-7xl font-semibold text-[var(--brand-text1)] tracking-tight leading-[1.05]">
            Ready to <br /> Start <span className="bg-gradient-to-r from-[#1B6C42] via-[#2D8F5C] to-[#1B6C42] bg-clip-text text-transparent landing-animate-gradient pr-2">Growing?</span>
          </h2>
          <p className="text-[var(--brand-text2)] text-lg mt-6 font-light">Join students who learn smarter, not harder.</p>
          <div className="mt-10 flex flex-col items-center">
            <button onClick={() => setShowOnboarding(true)} className="relative overflow-hidden group bg-[#1B6C42] text-white px-10 py-4 rounded-full font-medium text-base tracking-wide shadow-md hover:shadow-lg hover:bg-[#155A35] transition-all duration-500 hover:scale-[1.03] active:scale-[0.98] landing-btn-shimmer">
              Get Started
            </button>
          </div>
        </div>
      </section>

      {/* ═══ Footer ═══ */}
      <footer className="landing-section border-t border-white/35 py-12 px-8 relative z-10">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row items-center justify-between gap-6">
          <div className="flex items-center gap-2">
            <img src="/sapling-icon.svg" alt="Sapling" style={{ width: '20px', height: '20px' }} />
            <span className="text-sm font-light tracking-wide text-[var(--brand-text2)]">Sapling · © 2026</span>
          </div>
          <div className="flex flex-wrap justify-center gap-6">
            <a href="/about" className="text-[var(--brand-text2)] hover:text-[var(--brand-text1)] text-sm transition-colors">About</a>
            <a href="/careers" className="text-[var(--brand-text2)] hover:text-[var(--brand-text1)] text-sm transition-colors">Careers</a>
            <a href="/terms" className="text-[var(--brand-text2)] hover:text-[var(--brand-text1)] text-sm transition-colors">Terms of Service</a>
            <a href="/privacy" className="text-[var(--brand-text2)] hover:text-[var(--brand-text1)] text-sm transition-colors">Privacy Policy</a>
          </div>
        </div>
        <div className="max-w-7xl mx-auto mt-8 pt-6 border-t border-white/25 text-center">
          <p className="text-xs text-[var(--brand-text2)] opacity-75 font-light tracking-wide">
            © 2026 Andres Lopez, Jack He, Luke Cooper, and Jose Gael Cruz-Lopez. All Rights Reserved.
          </p>
        </div>
      </footer>

      {showOnboarding && (
        <OnboardingFlow
          visible={showOnboarding}
          onClose={() => setShowOnboarding(false)}
          onFinish={(formData) => {
            sessionStorage.setItem('sapling_onboarding', JSON.stringify(formData));
            router.replace('/dashboard');
          }}
          activeStep={activeStep}
          completed={completed}
          setActiveStep={setActiveStep}
          setCompleted={setCompleted}
        />
      )}
    </div>
  );
}
