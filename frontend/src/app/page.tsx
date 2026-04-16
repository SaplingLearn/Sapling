'use client';

import { useEffect, useState, useRef, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { useUser } from '@/context/UserContext';
import { Network, Sparkles, FilePlus2, Brain, CalendarClock, Users, PenSquare } from 'lucide-react';
import OnboardingFlow from '@/components/OnboardingFlow';
import HowItWorks from '@/components/HowItWorks';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:5000';

const SCRAMBLE_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!<>-_\\/[]{}=+*^?#_";

const CLUSTER_COLORS = ['#9CA3AF', '#D97706', '#3B82F6', '#8A63D2', '#14B8A6', '#EF4444'];
const CLUSTER_SEEDS_BG = [10.0, 11.3, 12.6, 13.9, 15.2, 16.5];
const CLUSTER_INIT_POS = [
  { ox: -222, oy: -29, oz:  15 },
  { ox: -161, oy: -59, oz: -20 },
  { ox:  -81, oy: -42, oz:  30 },
  { ox:  -67, oy:  17, oz:   0 },
  { ox: -168, oy:  59, oz:  20 },
  { ox: -229, oy:   8, oz: -30 },
];

export default function LandingPage() {
  const router = useRouter();
  const { userReady, isAuthenticated, userId } = useUser();

  const [heroMounted, setHeroMounted] = useState(false);
  const [heroText1, setHeroText1] = useState('');
  const [heroText2, setHeroText2] = useState('');
  const [onboardingPhase, setOnboardingPhase] = useState<'idle' | 'out' | 'active' | 'complete'>('idle');
  const [introText, setIntroText] = useState<'hidden' | 'in' | 'out'>('hidden');
  const [outroText, setOutroText] = useState<'hidden' | 'in' | 'out'>('hidden');
  const [outroOverlay, setOutroOverlay] = useState(false);
  const [activeStep, setActiveStep] = useState(0);
  const [completed, setCompleted] = useState<Set<number>>(new Set());

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const heroContentRef = useRef<HTMLDivElement>(null);
  const floatingCardsRef = useRef<HTMLDivElement>(null);
  const navRef = useRef<HTMLElement>(null);
  const ambientGlowRef = useRef<HTMLDivElement>(null);
  const parallaxYRef = useRef(0);
  const mouseRef = useRef({ x: 0, y: 0 });
  const onboardingTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const introTimeoutsRef = useRef<NodeJS.Timeout[]>([]);
  const canvasZoomRef = useRef(1.0);
  const zoomActiveRef = useRef(false);
  const zoomOutroRef = useRef(false);
  const onboardingPhaseRef = useRef<'idle' | 'out' | 'active' | 'complete'>('idle');
  const clusterProgressRef = useRef(0);
  const clusterActiveStepRef = useRef(0);
  const clusterCompletedRef = useRef<Set<number>>(new Set());
  const obNodesRef = useRef<Array<{
    ox: number; oy: number; oz: number;
    startOx: number; startOy: number; startOz: number;
    migDelay: number; migDur: number;
    color: string; radius: number; seed: number;
    birthTime: number; stepIndex: number; isPreview: boolean;
    dyingAt?: number;
  }>>([]);
  const obInitStepsRef = useRef<Set<number>>(new Set());
  const obDoneStepsRef = useRef<Set<number>>(new Set());

  // Auth redirect / onboarding resume
  useEffect(() => {
    if (userReady && isAuthenticated) {
      const pending = sessionStorage.getItem('sapling_onboarding_pending');
      if (pending) {
        sessionStorage.removeItem('sapling_onboarding_pending');
        window.scrollTo({ top: 0, behavior: 'instant' });
        setActiveStep(1);
        setCompleted(new Set([0]));
        setHeroMounted(true);
        setIntroText('hidden');
        zoomActiveRef.current = true;
        zoomOutroRef.current = false;
        canvasZoomRef.current = 2.5;
        clusterProgressRef.current = 1;
        setOnboardingPhase('active');
      } else {
        router.replace('/dashboard');
      }
    }
  }, [userReady, isAuthenticated, router]);

  // Cleanup timeouts on unmount
  useEffect(() => {
    return () => {
      if (onboardingTimeoutRef.current) clearTimeout(onboardingTimeoutRef.current);
      introTimeoutsRef.current.forEach(clearTimeout);
    };
  }, []);

  // Sync refs from state
  useEffect(() => {
    onboardingPhaseRef.current = onboardingPhase;
    document.body.style.overflow = onboardingPhase !== 'idle' ? 'hidden' : '';
    return () => { document.body.style.overflow = ''; };
  }, [onboardingPhase]);
  useEffect(() => { clusterActiveStepRef.current = activeStep; }, [activeStep]);
  useEffect(() => { clusterCompletedRef.current = completed; }, [completed]);

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

  // 3D Canvas graph with zoom + OB cluster nodes
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d', { alpha: true });
    if (!ctx) return;

    let width = 0, height = 0;
    let rotAngle = 0;
    let animId: number;

    const palette = [
      { c: '#8A63D2', w: 0.24 }, { c: '#3B82F6', w: 0.24 },
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

    // OB graph — cluster centres per onboarding step
    const OB_STEP_CENTERS = [
      { ox: -155, oy:   0, oz:   0 },
      { ox: -230, oy: -80, oz:  25 },
      { ox: -115, oy:-105, oz: -35 },
      { ox: -270, oy:  65, oz: -15 },
      { ox: -155, oy:  95, oz:  35 },
      { ox: -215, oy: -25, oz: -55 },
    ];
    const OB_SPREAD = 58;
    const OB_COUNT  = 15;
    const easeInOutCubic = (x: number) =>
      x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
    const stepRand = (si: number, idx: number) => {
      const s = Math.sin(si * 9301 + idx * 49297 + 233) * 10000003;
      return s - Math.floor(s);
    };

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
      const now = Date.now();

      // ── OB knowledge graph: spawn nodes per step ─────────────────────
      if (onboardingPhaseRef.current === 'active') {
        const asi = clusterActiveStepRef.current;
        if (!obInitStepsRef.current.has(asi)) {
          obInitStepsRef.current.add(asi);
          const ctr = OB_STEP_CENTERS[asi];
          for (let k = 0; k < 8; k++) {
            const ox = ctr.ox + (stepRand(asi, k * 4    ) - 0.5) * OB_SPREAD * 0.9;
            const oy = ctr.oy + (stepRand(asi, k * 4 + 1) - 0.5) * OB_SPREAD * 0.6;
            const oz = ctr.oz + (stepRand(asi, k * 4 + 2) - 0.5) * OB_SPREAD * 0.9;
            obNodesRef.current.push({
              ox, oy, oz, startOx: ox, startOy: oy, startOz: oz,
              migDelay: k * 60, migDur: 450,
              color: CLUSTER_COLORS[asi],
              radius: 1 + stepRand(asi, k * 4 + 3) * 1.5,
              seed: stepRand(asi, k * 4 + 2) * 100,
              birthTime: now, stepIndex: asi, isPreview: true,
            });
          }
        }
      }
      if (onboardingPhaseRef.current === 'active' || onboardingPhaseRef.current === 'complete') {
        const comp = clusterCompletedRef.current;
        comp.forEach(si => {
          if (!obDoneStepsRef.current.has(si)) {
            obDoneStepsRef.current.add(si);
            obNodesRef.current.forEach(n => {
              if (n.stepIndex === si && n.isPreview) n.dyingAt = now;
            });
            const ctr = OB_STEP_CENTERS[si];
            for (let k = 0; k < OB_COUNT; k++) {
              obNodesRef.current.push({
                ox: ctr.ox + (stepRand(si, k * 4    ) - 0.5) * OB_SPREAD * 2,
                oy: ctr.oy + (stepRand(si, k * 4 + 1) - 0.5) * OB_SPREAD * 1.5,
                oz: ctr.oz + (stepRand(si, k * 4 + 2) - 0.5) * OB_SPREAD * 2,
                startOx: 80 + stepRand(si, k * 4 + 10) * 260,
                startOy: (stepRand(si, k * 4 + 11) - 0.5) * 220,
                startOz: (stepRand(si, k * 4 + 12) - 0.5) * 220,
                migDelay: k * 50, migDur: 580 + stepRand(si, k * 4 + 13) * 160,
                color: CLUSTER_COLORS[si],
                radius: 1.8 + stepRand(si, k * 4 + 3) * 3,
                seed: stepRand(si, k * 4 + 2) * 100,
                birthTime: now, stepIndex: si, isPreview: false,
              });
            }
          }
        });
      }
      obNodesRef.current = obNodesRef.current.filter(n =>
        !(n.dyingAt !== undefined && now - n.dyingAt > 500)
      );
      if (onboardingPhaseRef.current === 'idle' && obNodesRef.current.length > 0) {
        obNodesRef.current = [];
        obInitStepsRef.current = new Set();
        obDoneStepsRef.current = new Set();
      }

      const zoomTarget = zoomOutroRef.current ? 5.5 : (zoomActiveRef.current ? 2.5 : 1.0);
      canvasZoomRef.current += (zoomTarget - canvasZoomRef.current) * 0.025;
      const zoom = canvasZoomRef.current;

      if (zoomActiveRef.current) {
        clusterProgressRef.current = Math.min(1, clusterProgressRef.current + 0.01);
      } else {
        clusterProgressRef.current = Math.max(0, clusterProgressRef.current - 0.015);
      }
      const clusterProgress = clusterProgressRef.current;

      const proj = nodes.map(n => {
        const ny = n.oy + Math.sin(t * 0.4 + n.seed) * 15;
        let x = n.ox * Math.cos(rotAngle) - n.oz * Math.sin(rotAngle);
        let z = n.oz * Math.cos(rotAngle) + n.ox * Math.sin(rotAngle);
        x -= mx * (z + fl) * 0.02;
        const y2 = ny - my * (z + fl) * 0.02;
        const sc = fl / (fl + z);
        return { x: x * sc * zoom + cx, y: y2 * sc * zoom + cy - parallaxYRef.current, z, sc: sc * zoom, n };
      }).sort((a, b) => b.z - a.z);

      ctx.globalCompositeOperation = 'source-over';
      ctx.lineWidth = 0.5;
      for (let i = 0; i < proj.length; i++) {
        for (let j = i + 1; j < proj.length; j++) {
          const p1 = proj[i], p2 = proj[j];
          const d = Math.hypot(p1.x - p2.x, p1.y - p2.y);
          if (d < 70 * p1.sc) {
            const a = (1 - d / (70 * p1.sc)) * 0.15 * Math.min(1, p1.sc) * Math.max(0, 1 - clusterProgress);
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
          let fogA = p.z > 500 ? Math.max(0, 1 - (p.z - 500) / 500) : 1;
          if (clusterProgress > 0) fogA *= Math.max(0.12, 1 - clusterProgress * 0.82);
          const r = p.n.radius * p.sc * breathe;
          if (r > 0.1) {
            ctx.globalAlpha = fogA;
            ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, Math.PI * 2); ctx.fillStyle = p.n.color; ctx.fill();
          }
        }
      });
      ctx.globalAlpha = 1;

      // ── OB knowledge graph: draw with migration ───────────────────────
      if (obNodesRef.current.length > 0) {
        const obProj = obNodesRef.current.flatMap(n => {
          const elapsed = now - n.birthTime;
          const rawMigP = (elapsed - n.migDelay) / n.migDur;
          if (rawMigP < 0) return [];
          const migP = Math.min(1, rawMigP);
          const easedM = easeInOutCubic(migP);
          const curOx = n.startOx + (n.ox - n.startOx) * easedM;
          const curOy = n.startOy + (n.oy - n.startOy) * easedM;
          const curOz = n.startOz + (n.oz - n.startOz) * easedM;
          const arrP = Math.min(1, Math.max(0, (elapsed - n.migDelay - n.migDur) / 400));
          const popScale = migP < 1 ? 0.4 + 0.6 * migP : 1.0 + Math.sin(arrP * Math.PI) * 0.12;
          const baseAlpha = migP < 1 ? easeInOutCubic(migP) : 1.0;
          const dyingFade = n.dyingAt !== undefined
            ? 1.0 - easeInOutCubic(Math.min(1, (now - n.dyingAt) / 350))
            : 1.0;
          const alpha = baseAlpha * dyingFade;
          if (alpha < 0.005) return [];
          const ny = curOy + Math.sin(t * 0.4 + n.seed) * 8 * migP;
          const rx = curOx * Math.cos(rotAngle) - curOz * Math.sin(rotAngle);
          const rz = curOz * Math.cos(rotAngle) + curOx * Math.sin(rotAngle);
          const sc = fl / (fl + rz);
          return [{ x: rx*sc*zoom+cx, y: ny*sc*zoom+cy-parallaxYRef.current, z: rz, sc, n, alpha, popScale, migP, arrP }];
        }).sort((a, b) => b.z - a.z);

        ctx.lineWidth = 0.7;
        for (let i = 0; i < obProj.length; i++) {
          for (let j = i + 1; j < obProj.length; j++) {
            const p1 = obProj[i], p2 = obProj[j];
            if (p1.migP < 1 || p2.migP < 1) continue;
            if (p1.alpha < 0.1 || p2.alpha < 0.1) continue;
            const d = Math.hypot(p1.x - p2.x, p1.y - p2.y);
            const maxD = 90 * p1.sc * zoom;
            if (d < maxD) {
              const a = (1 - d / maxD) * 0.35 * Math.min(p1.arrP, p2.arrP) * Math.min(p1.alpha, p2.alpha);
              if (a > 0.003) {
                const col = p1.n.color;
                const r = parseInt(col.slice(1, 3), 16);
                const g = parseInt(col.slice(3, 5), 16);
                const b = parseInt(col.slice(5, 7), 16);
                ctx.strokeStyle = (p1.n.isPreview && p2.n.isPreview)
                  ? `rgba(200,210,200,${(a * 0.35).toFixed(4)})`
                  : `rgba(${r},${g},${b},${a.toFixed(4)})`;
                ctx.beginPath(); ctx.moveTo(p1.x, p1.y); ctx.lineTo(p2.x, p2.y); ctx.stroke();
              }
            }
          }
        }

        obProj.forEach(p => {
          const breathe = 0.92 + 0.08 * Math.sin(t * 0.6 + p.n.seed);
          const r = Math.max(0.1, p.n.radius * p.sc * zoom * breathe * p.popScale);
          if (p.n.isPreview) {
            ctx.globalAlpha = (0.25 + 0.2 * Math.sin(t * 3 + p.n.seed)) * p.alpha;
            ctx.shadowBlur = 10;
          } else {
            ctx.globalAlpha = p.alpha;
            ctx.shadowBlur = p.migP >= 1 ? 18 * (0.7 + 0.3 * Math.sin(t * 1.5 + p.n.seed * 0.3)) : 6;
          }
          ctx.shadowColor = p.n.color;
          ctx.fillStyle = p.n.color;
          ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, Math.PI * 2); ctx.fill();
          ctx.shadowBlur = 0;
          ctx.shadowColor = 'transparent';
        });
        ctx.globalAlpha = 1;
      }

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

  // ── Onboarding phase transitions ──────────────────────────────────
  function startOnboarding() {
    if (onboardingTimeoutRef.current) clearTimeout(onboardingTimeoutRef.current);
    introTimeoutsRef.current.forEach(clearTimeout);
    window.scrollTo({ top: 0, behavior: 'instant' });
    setActiveStep(0);
    setCompleted(new Set());
    setIntroText('hidden');
    zoomActiveRef.current = false;
    zoomOutroRef.current = false;
    setOnboardingPhase('out');
    introTimeoutsRef.current = [
      setTimeout(() => setIntroText('in'), 450),
      setTimeout(() => {
        setIntroText('out');
        zoomActiveRef.current = true;
      }, 1900),
      setTimeout(() => {
        setIntroText('hidden');
        setOnboardingPhase('active');
      }, 2550),
    ];
  }

  function closeOnboarding() {
    if (onboardingTimeoutRef.current) clearTimeout(onboardingTimeoutRef.current);
    introTimeoutsRef.current.forEach(clearTimeout);
    introTimeoutsRef.current = [];
    zoomActiveRef.current = false;
    zoomOutroRef.current = false;
    setIntroText('hidden');
    const t = Date.now();
    obNodesRef.current.forEach(n => { if (n.dyingAt === undefined) n.dyingAt = t; });
    setOnboardingPhase('out');
    onboardingTimeoutRef.current = setTimeout(() => setOnboardingPhase('idle'), 700);
  }

  async function handleOnboardingComplete(formData: { firstName: string; lastName: string; school: string; year: string; majors: string[]; minors: string[]; course_ids: string[]; style: string }) {
    // Persist onboarding data to Supabase
    try {
      await fetch(`${API_URL}/api/onboarding/profile`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: userId,
          first_name: formData.firstName,
          last_name: formData.lastName,
          year: formData.year,
          majors: formData.majors,
          minors: formData.minors,
          course_ids: formData.course_ids,
          learning_style: formData.style,
        }),
      });
    } catch (e) {
      console.error('Failed to save onboarding profile:', e);
    }

    introTimeoutsRef.current.forEach(clearTimeout);
    zoomActiveRef.current = true;
    zoomOutroRef.current = false;
    setOutroText('hidden');
    setOutroOverlay(false);
    setOnboardingPhase('complete');
    introTimeoutsRef.current = [
      setTimeout(() => setOutroText('in'), 1400),
      setTimeout(() => {
        setOutroText('out');
        zoomOutroRef.current = true;
      }, 3050),
      setTimeout(() => setOutroOverlay(true), 3450),
      setTimeout(() => { router.replace('/dashboard'); }, 4250),
    ];
  }

  const authIdle = userReady && isAuthenticated && onboardingPhase === 'idle';

  return (
    <div className="landing-page antialiased" style={{ fontFamily: "var(--font-inter), 'Inter', sans-serif", color: 'var(--brand-text1, #1a1a1a)', background: 'transparent', opacity: authIdle ? 0 : 1, pointerEvents: authIdle ? 'none' : 'auto' }}>
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
          opacity: onboardingPhase !== 'idle' ? 0 : (heroMounted ? 1 : 0),
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
            <button onClick={startOnboarding} className="relative overflow-hidden group bg-[#1B6C42] text-white px-7 py-2.5 rounded-full font-medium text-sm tracking-wide shadow-sm hover:shadow-md transition-all duration-400 hover:scale-[1.04] active:scale-[0.97] landing-btn-shimmer">
              Get Started
            </button>
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
        <div ref={floatingCardsRef} className="absolute inset-0 z-10 hidden lg:block pointer-events-none"
          style={{ opacity: onboardingPhase !== 'idle' ? 0 : 1, transition: 'opacity 600ms ease' }}
        >
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
        <div ref={heroContentRef} className="relative z-20 flex flex-col items-center text-center max-w-4xl px-6"
          style={{ opacity: onboardingPhase !== 'idle' ? 0 : 1, transition: 'opacity 600ms ease' }}
        >
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
            <button onClick={startOnboarding} className="relative overflow-hidden group bg-[#1B6C42] text-white px-10 py-4 rounded-full font-medium text-base tracking-wide shadow-md hover:shadow-lg hover:bg-[#155A35] transition-all duration-500 hover:scale-[1.03] active:scale-[0.98] landing-btn-shimmer">
              Get Started
            </button>
            <button onClick={() => document.getElementById('features')?.scrollIntoView({ behavior: 'smooth' })} className="liquid-glass-subtle text-[var(--brand-text2)] hover:text-[var(--brand-text1)] px-10 py-4 rounded-full font-medium text-base transition-all duration-500 hover:scale-[1.02] active:scale-[0.98]">
              See What&apos;s Inside <span className="ml-1 opacity-50">↓</span>
            </button>
          </div>
        </div>

        {/* Scroll Indicator */}
        <div style={{ opacity: onboardingPhase !== 'idle' ? 0 : (heroMounted ? 1 : 0), transition: 'opacity 1s ease 1.2s' }} className="absolute bottom-8 left-1/2 landing-animate-float-indicator flex flex-col items-center">
          <div className="w-px h-14 landing-divider-v" />
          <span className="font-jetbrains text-xs tracking-[0.4em] text-[var(--brand-text2)] opacity-70 mt-3">SCROLL</span>
        </div>
      </section>

      {/* ═══ Features Section ═══ */}
      <div style={{ opacity: onboardingPhase !== 'idle' ? 0 : 1, transition: 'opacity 600ms ease', pointerEvents: onboardingPhase !== 'idle' ? 'none' : 'auto' }}>
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
              <button onClick={startOnboarding} className="relative overflow-hidden group bg-[#1B6C42] text-white px-10 py-4 rounded-full font-medium text-base tracking-wide shadow-md hover:shadow-lg hover:bg-[#155A35] transition-all duration-500 hover:scale-[1.03] active:scale-[0.98] landing-btn-shimmer">
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
      </div>

      {/* ═══ Intro title reveal ═══ */}
      {onboardingPhase !== 'idle' && (
        <div
          style={{
            position: 'fixed', inset: 0, zIndex: 75,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            pointerEvents: 'none',
            opacity: introText === 'in' ? 1 : 0,
            transition: 'opacity 650ms cubic-bezier(0.22,1,0.36,1)',
          }}
        >
          <div style={{
            position: 'absolute',
            width: '680px', height: '260px',
            background: 'radial-gradient(ellipse at center, rgba(255,255,255,0.62) 0%, rgba(255,255,255,0.28) 45%, transparent 72%)',
            pointerEvents: 'none',
          }} />
          <p style={{
            position: 'relative',
            fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif",
            fontSize: 'clamp(26px, 4vw, 50px)',
            fontWeight: 300,
            color: '#0f172a',
            textShadow: '0 1px 2px rgba(255,255,255,0.9)',
            letterSpacing: '0.01em',
            textAlign: 'center',
            lineHeight: 1.3,
            margin: 0,
          }}>
            Let&apos;s Learn About You...
          </p>
        </div>
      )}

      {/* ═══ Outro: Welcome to Sapling ═══ */}
      {onboardingPhase === 'complete' && (
        <div
          style={{
            position: 'fixed', inset: 0, zIndex: 76,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            pointerEvents: 'none',
            opacity: outroText === 'in' ? 1 : 0,
            transition: 'opacity 700ms cubic-bezier(0.22,1,0.36,1)',
          }}
        >
          <div style={{
            position: 'absolute',
            width: '780px', height: '280px',
            background: 'radial-gradient(ellipse at center, rgba(255,255,255,0.65) 0%, rgba(255,255,255,0.28) 45%, transparent 72%)',
            pointerEvents: 'none',
          }} />
          <p style={{
            position: 'relative',
            fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif",
            fontSize: 'clamp(30px, 5vw, 62px)',
            fontWeight: 300,
            color: '#0f172a',
            textShadow: '0 1px 2px rgba(255,255,255,0.9)',
            letterSpacing: '0.01em',
            textAlign: 'center',
            lineHeight: 1.2,
            margin: 0,
          }}>
            Welcome to Sapling
          </p>
        </div>
      )}

      {/* ═══ Outro white overlay ═══ */}
      <div style={{
        position: 'fixed', inset: 0, zIndex: 92,
        background: 'white',
        opacity: outroOverlay ? 1 : 0,
        transition: 'opacity 900ms cubic-bezier(0.4,0,0.2,1)',
        pointerEvents: 'none',
      }} />

      {/* ═══ Onboarding flow ═══ */}
      {onboardingPhase !== 'idle' && (
        <OnboardingFlow
          visible={onboardingPhase === 'active'}
          onClose={closeOnboarding}
          onFinish={handleOnboardingComplete}
          activeStep={activeStep}
          completed={completed}
          setActiveStep={setActiveStep}
          setCompleted={setCompleted}
        />
      )}
    </div>
  );
}
