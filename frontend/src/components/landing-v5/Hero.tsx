'use client';

/**
 * The landing hero — main's title screen, carried onto the v5 page.
 *
 * The v5 port's own hero (the DM Sans lede row, the WebGL panel rig in
 * `lib/landing/hero3d`, the info box and SCROLL TO EXPLORE cue) was judged not
 * good enough for the top of the page, so this is the hero `main` ships,
 * lifted out of the page component it used to live in and made a section of
 * its own. Everything below it — the descent band, the acts, the gallery, the
 * journal, the closing — is v5's and untouched.
 *
 * What this keeps from main: the rotating 2D point-cloud canvas, the two
 * floating knowledge-state cards, the Playfair wordmark + tagline (the
 * wordmark a size up from main's 10rem), the beta CTA and the SEE WHAT'S
 * INSIDE cue, and the mouse tilt + scroll parallax that ties them together.
 * What it takes from v5: the lede between the tagline and the CTA, which is
 * v5's copy verbatim. What it no longer owns: the intro overlay,
 * the navbar and the beta modal, which the v5 page provides. The wordmark and
 * tagline arrive through `useLanding`'s intro scramble rather than a timer of
 * this component's own, so the hero cascades in exactly as the v5 overlay
 * clears.
 *
 * The section carries `.landing-page` so main's scoped landing CSS (the mesh
 * blobs, the panel surfaces, the marketing tokens) applies inside it without
 * being re-declared for `.landing-v5`; the v5 root sets the same #f0f4f2
 * ground, so the scope's own background is a no-op.
 */

import { useEffect, useRef } from 'react';
import { PenSquare, Users } from 'lucide-react';
import { Button } from '@/components/ui';
import { IS_TEST_MODE, now, random } from '@/lib/testMode';

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

export function Hero({
  heroMounted,
  heroText1,
  heroText2,
  onBeta,
}: {
  /** True once the intro overlay has cleared and the hero may rise. */
  heroMounted: boolean;
  /** The wordmark, mid-scramble or settled. */
  heroText1: string;
  /** The tagline under it, likewise. */
  heroText2: string;
  onBeta: () => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const heroContentRef = useRef<HTMLDivElement>(null);
  const floatingCardsRef = useRef<HTMLDivElement>(null);
  const parallaxYRef = useRef(0);
  const mouseRef = useRef({ x: 0, y: 0 });

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
    // Test mode parks the loop on its single deterministic frame, same
    // as prefers-reduced-motion.
    let animating = !IS_TEST_MODE && !reduceMotion.matches;

    // #3e6f8a mirrors --info (globals.css); literal because canvas can't resolve var().
    const palette = [
      { c: '#8A63D2', w: 0.24 }, { c: '#3e6f8a', w: 0.24 },
      { c: '#D97706', w: 0.20 }, { c: '#14B8A6', w: 0.15 },
      { c: '#9CA3AF', w: 0.10 }, { c: '#D1D5DB', w: 0.07 },
    ];
    function randColor() {
      const r = random();
      let s = 0;
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
      const cl = clusters[Math.floor(random() * clusters.length)];
      return {
        ox: cl.x + (random() - 0.5) * spread,
        oy: cl.y + (random() - 0.5) * spread,
        oz: cl.z + (random() - 0.5) * spread,
        color: randColor(),
        radius: 1 + random() * 4,
        seed: random() * 100,
        clusterIndex: undefined as number | undefined,
      };
    });
    const clusterNodes = CLUSTER_INIT_POS.map((pos, i) => ({
      ox: pos.ox, oy: pos.oy, oz: pos.oz,
      color: CLUSTER_COLORS[i],
      radius: 2.5 + random() * 1.5,
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
      const fl = 1000, cx = width / 2, cy = height / 2, t = now() * 0.001;
      const mx = mouseRef.current.x, my = mouseRef.current.y;

      const proj = nodes.map(n => {
        const ny = n.oy + Math.sin(t * 0.4 + n.seed) * 15;
        let x = n.ox * Math.cos(rotAngle) - n.oz * Math.sin(rotAngle);
        const z = n.oz * Math.cos(rotAngle) + n.ox * Math.sin(rotAngle);
        x -= mx * (z + fl) * 0.02;
        const y2 = ny - my * (z + fl) * 0.02;
        const sc = fl / (fl + z);
        return { x: x * sc + cx, y: y2 * sc + cy - parallaxYRef.current, z, sc, n };
      }).sort((a, b) => b.z - a.z);

      ctx.globalCompositeOperation = 'source-over';
      ctx.lineWidth = 0.5;
      // The pair walk itself is unavoidable (links depend on projected
      // positions, which change every frame), but almost every pair fails the
      // distance test — so make failing cheap: hoist the per-node threshold
      // out of the inner loop, reject on |dx|/|dy| before multiplying, and
      // compare squared distances so the sqrt only runs for pairs that
      // actually draw a link.
      for (let i = 0; i < proj.length; i++) {
        const p1 = proj[i];
        const maxD = 70 * p1.sc;
        const maxD2 = maxD * maxD;
        const aScale = 0.15 * Math.min(1, p1.sc);
        for (let j = i + 1; j < proj.length; j++) {
          const p2 = proj[j];
          const dx = p1.x - p2.x;
          if (dx > maxD || dx < -maxD) continue;
          const dy = p1.y - p2.y;
          if (dy > maxD || dy < -maxD) continue;
          const d2 = dx * dx + dy * dy;
          if (d2 < maxD2) {
            const a = (1 - Math.sqrt(d2) / maxD) * aScale;
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
      const next = !IS_TEST_MODE && !reduceMotion.matches;
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

  // Mouse + scroll. On main this handler also drove the navbar's auto-hide
  // and the page-wide ambient glow; both are the v5 page's business now
  // (`useLanding` hides the nav, the ambient canvas replaces the glow), so
  // only the hero's own parallax is left.
  useEffect(() => {
    const onMouse = (e: MouseEvent) => {
      mouseRef.current = { x: (e.clientX / window.innerWidth - 0.5) * 2, y: (e.clientY / window.innerHeight - 0.5) * 2 };
    };

    const applyScroll = () => {
      const sy = window.scrollY;
      if (heroContentRef.current && sy < window.innerHeight) {
        heroContentRef.current.style.transform = `translateY(${sy * -0.3}px)`;
        parallaxYRef.current = sy * 0.1;
      }
    };

    // Scroll fires far more often than the compositor paints, and each call
    // writes inline styles. Coalesce to one write per frame.
    let queued = 0;
    const onScroll = () => {
      if (queued) return;
      queued = requestAnimationFrame(() => { queued = 0; applyScroll(); });
    };

    document.addEventListener('mousemove', onMouse, { passive: true });
    window.addEventListener('scroll', onScroll, { passive: true });
    applyScroll();
    return () => {
      document.removeEventListener('mousemove', onMouse);
      window.removeEventListener('scroll', onScroll);
      cancelAnimationFrame(queued);
    };
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
    let animating = !IS_TEST_MODE && !reduceMotion.matches;

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
      const next = !IS_TEST_MODE && !reduceMotion.matches;
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

  return (
    <section
      className="landing-page antialiased relative min-h-svh flex items-center justify-center"
      style={{ fontFamily: 'var(--font-inter), sans-serif', color: 'var(--text, #1a1a1a)', background: 'transparent' }}
    >
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
          {/*
            Canonical knowledge-status tokens (globals.css:80-89), not literals
            (#344 visual 1b). These four swatches and the graph act's node
            colours are one viewport apart on the same page, so they have to be
            the same palette — and it has to be the palette the signed-in
            product actually uses. Colours only; nothing else in the hero moves.
          */}
          <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2"><div className="w-2 h-2 rounded-full bg-[var(--state-mastery)]" /><span className="text-xs text-[var(--text-dim)] uppercase tracking-wide">Mastered</span></div>
            <div className="flex items-center gap-2"><div className="w-2 h-2 rounded-full bg-[var(--state-progress)]" /><span className="text-xs text-[var(--text-dim)] uppercase tracking-wide">Learning</span></div>
            <div className="flex items-center gap-2"><div className="w-2 h-2 rounded-full bg-[var(--state-struggle)]" /><span className="text-xs text-[var(--text-dim)] uppercase tracking-wide">Struggling</span></div>
            <div className="flex items-center gap-2"><div className="w-2 h-2 rounded-full bg-[var(--state-neutral)]" /><span className="text-xs text-[var(--text-dim)] uppercase tracking-wide">Unexplored</span></div>
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

      {/* Bottom legibility band — the one v5 idea this hero borrows. On main the
          hero sat on a mesh that ran the whole page, so its blobs and point
          cloud could trail off however they liked; here the opaque descent
          band below starts on a flat #F0F4F2, and a blurred blob cut dead at
          that edge reads as a seam. Fade everything to that exact colour before
          the boundary instead. Above the canvas and the cards, below the copy. */}
      <div
        aria-hidden
        className="absolute inset-x-0 bottom-0 z-10 pointer-events-none"
        style={{
          height: '26%',
          background: 'linear-gradient(0deg, #F0F4F2 0%, rgba(240,244,242,0.9) 22%, rgba(240,244,242,0.55) 55%, rgba(240,244,242,0) 100%)',
        }}
      />

      {/* Hero Content */}
      <div ref={heroContentRef} className="relative z-20 flex flex-col items-center text-center max-w-4xl px-6">
        {/* Legibility veil. The point cloud runs straight through the copy and
            was breaking the letterforms, so the copy sits on a slight blur of
            whatever is behind it plus a wash of the page colour. Both are
            feathered by a radial mask so there is no edge — the dots just go
            soft and pale as they pass under the text. Sits below the text in
            this block's own stacking context (the block is z-20), above the
            canvas and cards. */}
        <div
          aria-hidden
          className="absolute -z-10 pointer-events-none"
          style={{
            inset: '-10% -16%',
            backdropFilter: 'blur(4px)',
            WebkitBackdropFilter: 'blur(4px)',
            background:
              'radial-gradient(ellipse at center, rgba(240,244,242,0.6) 0%, rgba(240,244,242,0.45) 55%, rgba(240,244,242,0.2) 100%)',
            // Two linear fades intersected, not one radial: a radial mask
            // thinned out over the S and the g, so the ends of the wordmark
            // sat in sharp dots while the middle sat in soft ones. This holds
            // full strength across the whole block and feathers only at the
            // outer margin the negative inset adds.
            maskImage:
              'linear-gradient(90deg, transparent 0%, #000 14%, #000 86%, transparent 100%), linear-gradient(180deg, transparent 0%, #000 16%, #000 84%, transparent 100%)',
            WebkitMaskImage:
              'linear-gradient(90deg, transparent 0%, #000 14%, #000 86%, transparent 100%), linear-gradient(180deg, transparent 0%, #000 16%, #000 84%, transparent 100%)',
            maskComposite: 'intersect',
            WebkitMaskComposite: 'source-in',
          }}
        />
        {/* The wordmark scrambles in client-side, so the accessible name is
            the only server-rendered trace of it — public-seo.spec pins that. */}
        <h1 aria-label="Sapling" style={{
          opacity: heroMounted ? 1 : 0,
          transform: heroMounted ? 'translateY(0)' : 'translateY(25px)',
          transition: 'all 700ms cubic-bezier(0.22,1,0.36,1) 300ms',
        }} className="font-playfair text-[clamp(4rem,13.5vw,13rem)] font-semibold leading-[1.1] pb-[0.115em] tracking-tight px-4 text-[var(--brand-forest)]">
          <span>{heroText1 || ' '}</span>
        </h1>

        <p style={{
          opacity: heroMounted ? 1 : 0,
          transform: heroMounted ? 'translateY(0)' : 'translateY(25px)',
          transition: 'all 700ms cubic-bezier(0.22,1,0.36,1) 500ms',
        }} className="font-playfair text-2xl sm:text-3xl md:text-4xl text-[var(--text-dim)] max-w-xl mx-auto mt-2 leading-[1.2] tracking-tight font-medium">
          {heroText2 || ' '}
        </p>

        {/* The lede is the one line of v5's hero kept: what Sapling does. The
            second sentence is v5's verbatim; v5's third sentence ran the lede
            to four lines and was cut as too long, and its two-word opener
            ("Upload a syllabus.") was replaced by request with a fuller one. */}
        {/* Vertical rhythm, from the "Hero Rhythm" canvas in the Sapling landing
            design project (option 1c, "widening"): the wordmark's bottom padding
            is exactly Playfair's descender overflow at 1.1 leading, so the box
            ends on the g and p and the gaps below are true visual gaps — and
            they grow as importance drops: 8 to the tagline (one lockup), 32 to
            the lede, 52 to the CTA. The tagline is display type at 1.2, not
            body leading. The wordmark is fluid and capped at 13rem because a
            fixed 208px ran into the right-hand card at 1440px wide. */}
        <p style={{
          opacity: heroMounted ? 1 : 0,
          transform: heroMounted ? 'translateY(0)' : 'translateY(25px)',
          transition: 'all 700ms cubic-bezier(0.22,1,0.36,1) 650ms',
        }} className="font-dm-sans text-base md:text-lg font-medium text-[var(--text)] max-w-[560px] mx-auto mt-6 md:mt-8 leading-[1.55] text-pretty">
          Start with the syllabus for the class you&apos;re taking right now. Sapling reads your
          whole course, learns what you know, and drills what is slipping.
        </p>

        <div style={{
          opacity: heroMounted ? 1 : 0,
          transform: heroMounted ? 'translateY(0)' : 'translateY(25px)',
          transition: 'all 700ms cubic-bezier(0.22,1,0.36,1) 800ms',
        }} className="flex flex-col items-center gap-4 mt-10 md:mt-[52px]">
          <div style={{ position: 'relative', display: 'inline-flex', flexDirection: 'column', alignItems: 'center', gap: 6 }}>
            <Button variant="primary" size="xl" onClick={onBeta}>
              Sign up for Beta Testing
            </Button>
          </div>
        </div>
      </div>

      {/* Scroll Indicator */}
      <div style={{ opacity: heroMounted ? 1 : 0, transition: 'opacity 1s ease 1.2s' }} className="absolute bottom-8 left-1/2 z-20 landing-animate-float-indicator flex flex-col items-center">
        <div className="w-px h-14 landing-divider-v" />
        <span className="font-jetbrains text-xs tracking-[0.4em] whitespace-nowrap text-[var(--text-dim)] opacity-70 mt-3">SEE WHAT&apos;S INSIDE</span>
      </div>
    </section>
  );
}
