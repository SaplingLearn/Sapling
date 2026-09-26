'use client';

/**
 * The Sapling landing page.
 *
 * Ported from `Sapling Landing v5.dc.html`. This is the page at `/` — it
 * replaced the previous marketing landing outright rather than sitting
 * beside it.
 *
 * The hero is the exception: the v5 title screen was judged not good enough
 * for the top of the page, so `Hero` is main's hero (the point-cloud canvas,
 * the floating cards, the Playfair wordmark) carried over as a section of its
 * own. Everything from the descent band down is v5's.
 *
 * Sections land incrementally; the engine drives whatever is mounted.
 *
 * This page also hosts the onboarding choreography: a new account is set up in
 * place here rather than on the plain `/onboarding` card route. The hero dims,
 * its canvas dives into a knowledge graph, and `OnboardingFlow` rides on top
 * while each answered step flies its own colour cluster in. The canvas half
 * lives in `landing-v5/onboardingChoreography.ts`; this file owns the phase
 * machine and the two entry points. `/onboarding` stays mounted as the
 * standalone fallback.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useUser } from '@/context/UserContext';
import { useScrollLock } from '@/lib/useScrollLock';
import { now } from '@/lib/testMode';
import { submitOnboardingProfile, type OnboardingProfilePayload } from '@/lib/api';
import SignInModal from '@/components/marketing/SignInModal';
import OnboardingFlow from '@/components/marketing/OnboardingFlow';
import { ActGraph, RiseBand } from '@/components/landing-v5/ActGraph';
import { ActIngest } from '@/components/landing-v5/ActIngest';
import { BetaModal } from '@/components/landing-v5/BetaModal';
import { ActTutor } from '@/components/landing-v5/ActTutor';
import { FinalCta, SiteFooter } from '@/components/landing-v5/Closing';
import { Faq } from '@/components/landing-v5/Faq';
import { FeatureLab } from '@/components/landing-v5/FeatureLab';
import { Journal } from '@/components/landing-v5/Journal';
import { Gallery } from '@/components/landing-v5/Gallery';
import { Hero } from '@/components/landing-v5/Hero';
import { IntroOverlay } from '@/components/landing-v5/IntroOverlay';
import { Navbar } from '@/components/landing-v5/Navbar';
import { NAV_LIGHT } from '@/components/landing-v5/navTheme';
import {
  armObOutro, armObZoom, obCanvasAnimating, releaseObZoom, resetObGraph,
  retireObNodes, syncObState, useObRefs, type ObPhase,
} from '@/components/landing-v5/onboardingChoreography';
import { useLanding, type ScrambleStep } from '@/components/landing/useLanding';

/**
 * Main's hero cascade: the wordmark leads and the tagline follows 200ms
 * behind, on the slots main's hero reads (1 = wordmark, 2 = tagline). v5's
 * default runs the other way round on slots 0/1, for a title screen that is
 * no longer mounted.
 */
const HERO_CASCADE: ScrambleStep[] = [
  { slot: 1, text: 'Sapling', durationMs: 1000 },
  { slot: 2, text: 'Grow Your Knowledge', durationMs: 1200, delayMs: 200 },
];

/** Where the onboarding text beats sit, in ms from the intro's start. */
const OB_INTRO_IN = 450;
const OB_INTRO_OUT = 1900;
const OB_FORM_IN = 2550;

export default function LandingPage() {
  const {
    rootRef, ambientCanvasRef, navRef,
    actCanvasRef, cinemaRef, ingestSceneRef, ingestStageRef, carouselRef, trackARef, trackBRef,
    state, set, actions,
  } = useLanding({ loadCounter: true, cascade: HERO_CASCADE });

  const router = useRouter();
  const { userId, userReady, isAuthenticated } = useUser();

  // Carried over from the page this replaced: the nav's Sign In still opens
  // the real OAuth modal rather than scrolling somewhere.
  const [signInOpen, setSignInOpen] = useState(false);
  // Added by request. The design scrolls both beta CTAs down to the
  // newsletter section instead; they open this dialog now.
  const [betaOpen, setBetaOpen] = useState(false);

  // ── Onboarding choreography ─────────────────────────────────────────
  const ob = useObRefs();
  const [obPhase, setObPhase] = useState<ObPhase>('idle');
  const [introText, setIntroText] = useState<'hidden' | 'in' | 'out'>('hidden');
  const [outroText, setOutroText] = useState<'hidden' | 'in' | 'out'>('hidden');
  const [outroOverlay, setOutroOverlay] = useState(false);
  const [obStep, setObStep] = useState(0);
  const [obDone, setObDone] = useState<Set<number>>(new Set());
  const obTimersRef = useRef<ReturnType<typeof setTimeout>[]>([]);
  // Bumped by each request to enter onboarding, so the effect below re-fires
  // even when nothing else about the page has changed.
  const [obRequest, setObRequest] = useState(0);

  const clearObTimers = useCallback(() => {
    obTimersRef.current.forEach(clearTimeout);
    obTimersRef.current = [];
  }, []);

  /**
   * Dim the hero, play "Let's Learn About You…", then let the canvas lerp its
   * zoom 1.0 → 2.5 and form the clusters before dropping into the form.
   * Shared by both entry points so neither snaps straight to the zoomed form.
   */
  const playOnboardingIntro = useCallback(() => {
    clearObTimers();
    window.scrollTo({ top: 0, behavior: 'instant' });
    setObStep(0);
    setObDone(new Set());
    setIntroText('hidden');
    // Start from the un-zoomed state so the zoom-in actually animates rather
    // than snapping (the bug: the resume path used to hard-set these to 2.5/1).
    resetObGraph(ob);

    // Reduced motion / test mode: the hero's canvas RAF is parked on one
    // deterministic frame, so there is no zoom to watch and no timing to wait
    // on. Skip the choreography and open the form — the flow still works, it
    // just doesn't perform. (#111 / #383 take this position for the hero loops.)
    if (!obCanvasAnimating(ob)) {
      setObPhase('active');
      return;
    }

    setObPhase('out');
    obTimersRef.current = [
      setTimeout(() => setIntroText('in'), OB_INTRO_IN),
      setTimeout(() => {
        setIntroText('out');
        armObZoom(ob);
      }, OB_INTRO_OUT),
      setTimeout(() => {
        setIntroText('hidden');
        setObPhase('active');
      }, OB_FORM_IN),
    ];
  }, [clearObTimers, ob]);

  /**
   * Both entry points converge here.
   *
   * - Popup sign-in dispatches `sapling:start-onboarding` to this already-
   *   mounted page (see SignInModal.onmessage). `isAuthenticated` may not
   *   change for a returning visitor, so an effect keyed on it cannot fire.
   * - The same-tab Google redirect sets `sapling_onboarding_pending` in
   *   auth/callback and lands back here on a fresh mount.
   *
   * The two never both run for one sign-in. Either way the intro waits for
   * `heroMounted`: until then the load overlay owns the screen and the first
   * beat would play underneath it.
   */
  useEffect(() => {
    const pending = userReady && isAuthenticated
      && sessionStorage.getItem('sapling_onboarding_pending') !== null;
    if (!pending && obRequest === 0) return;
    if (!state.heroMounted) return;
    // Next tick rather than inside this pass: the intro sets state, and the
    // sequence is timer-driven from the first beat anyway.
    const t = setTimeout(playOnboardingIntro, 0);
    return () => clearTimeout(t);
  }, [userReady, isAuthenticated, obRequest, state.heroMounted, playOnboardingIntro]);

  // The popup path's signal. Routed through the same request counter as every
  // other entry, so it waits for `heroMounted` the same way.
  useEffect(() => {
    const onStart = () => setObRequest(n => n + 1);
    window.addEventListener('sapling:start-onboarding', onStart);
    return () => window.removeEventListener('sapling:start-onboarding', onStart);
  }, []);

  // Consume the pending flag only once the intro has actually reached the form
  // — past React's Strict-Mode mount double-invoke, which would otherwise
  // clear the intro's timers before they fire and strand the flow at 'out'.
  // Harmless no-op for paths that never set the flag.
  useEffect(() => {
    if (obPhase === 'active') sessionStorage.removeItem('sapling_onboarding_pending');
  }, [obPhase]);

  // Mirror the phase machine into the frame loop.
  useEffect(() => { syncObState(ob, { phase: obPhase }); }, [obPhase, ob]);
  useEffect(() => { syncObState(ob, { activeStep: obStep }); }, [obStep, ob]);
  useEffect(() => { syncObState(ob, { completed: obDone }); }, [obDone, ob]);

  useEffect(() => clearObTimers, [clearObTimers]);

  function startOnboarding() {
    if (!userReady) return;
    if (!isAuthenticated) {
      // Not signed in yet — just open the modal. After Google completes, one of
      // the two entry points above resumes without this pre-stashing anything.
      setSignInOpen(true);
      return;
    }
    setObRequest(n => n + 1);
  }

  const closeOnboarding = useCallback(() => {
    clearObTimers();
    releaseObZoom(ob);
    setIntroText('hidden');
    retireObNodes(ob, now());
    setObPhase('out');
    obTimersRef.current = [setTimeout(() => setObPhase('idle'), 700)];
  }, [clearObTimers, ob]);

  async function handleOnboardingComplete(formData: {
    firstName: string; lastName: string; school: string; year: string;
    majors: string[]; minors: string[]; course_ids: string[]; style: string;
  }) {
    // Persist via the shared same-origin helper. A raw fetch to
    // NEXT_PUBLIC_API_URL (a cross-origin subdomain) drops the sapling_session
    // cookie, so require_self 401s and onboarding_completed never flips —
    // trapping the user in the "Get Started" flow on every sign-in.
    // submitOnboardingProfile goes through fetchJSON (same-origin proxy +
    // credentials + res.ok check).
    try {
      await submitOnboardingProfile({
        user_id: userId,
        first_name: formData.firstName,
        last_name: formData.lastName,
        year: formData.year,
        majors: formData.majors,
        minors: formData.minors,
        course_ids: formData.course_ids,
        learning_style: formData.style as OnboardingProfilePayload['learning_style'],
      });
    } catch (e) {
      console.error('Failed to save onboarding profile:', e);
    }

    clearObTimers();
    armObZoom(ob);
    setOutroText('hidden');
    setOutroOverlay(false);
    setObPhase('complete');
    obTimersRef.current = [
      setTimeout(() => setOutroText('in'), 1400),
      setTimeout(() => {
        setOutroText('out');
        armObOutro(ob);
      }, 3050),
      setTimeout(() => setOutroOverlay(true), 3450),
      setTimeout(() => router.replace('/dashboard'), 4250),
    ];
  }

  const onboarding = obPhase !== 'idle';

  // The document scrollbar is hidden while the landing is mounted: the page
  // is a guided scroll cinema and the bar reads as stray chrome against the
  // full-bleed grounds. Scrolling itself is untouched.
  useEffect(() => {
    document.documentElement.classList.add('ld-noscrollbar');
    return () => document.documentElement.classList.remove('ld-noscrollbar');
  }, []);

  // Pre-auth there is no app shell, so <body> is the real scroll container.
  // The choreography owns the viewport; scrolling out of it mid-flow would
  // leave the form floating over the graph act.
  useScrollLock(onboarding);

  // Pinned light: since the graph act moved onto the light ground there is
  // no full-bleed dark section left for the bar to invert over. The dark
  // table and the scroll rule live on in navTheme.ts if one returns.
  const navTheme = NAV_LIGHT;

  return (
    <div
      ref={rootRef}
      className="landing-dc landing-v5"
      style={{
        fontFamily: "'DM Sans',system-ui,sans-serif", color: '#12201A', fontSize: 14,
        lineHeight: 1.6, backgroundColor: '#f0f4f2',
        backgroundImage:
          'radial-gradient(ellipse 100% 60% at 50% -10%, rgba(255,255,255,0.55) 0%, transparent 50%), radial-gradient(ellipse 80% 50% at 100% 40%, rgba(255,255,255,0.2) 0%, transparent 45%)',
        minHeight: '100vh', overflowX: 'clip',
      }}
    >
      {/* ambient constellation, behind everything. Fades for the choreography:
          the hero's own canvas is doing the diving, and a second field holding
          still behind it reads as two graphs at once. */}
      <canvas
        ref={ambientCanvasRef}
        aria-hidden="true"
        style={{
          position: 'fixed', inset: 0, zIndex: -1, width: '100%', height: '100%',
          pointerEvents: 'none',
          opacity: onboarding ? 0 : 1, transition: 'opacity 600ms ease',
        }}
      />

      <IntroOverlay
        heroMounted={state.heroMounted}
        introGone={state.introGone}
        loadPct={state.loadPct}
      />

      {/* The bar hides for the graph act's explore mode and for onboarding
          alike — both take the whole screen over. */}
      <Navbar
        navRef={navRef}
        heroMounted={state.heroMounted}
        exploring={state.exploring || onboarding}
        theme={navTheme}
        onLogoClick={actions.scrollTop}
        onSignIn={() => setSignInOpen(true)}
        // Restored to the job it had on main: the nav's Get Started enters
        // onboarding (signing in first if it has to). The beta CTAs — the
        // hero's and the closing one — still open the beta dialog.
        onGetStarted={startOnboarding}
      />

      <SignInModal open={signInOpen} onClose={() => setSignInOpen(false)} />

      <BetaModal
        open={betaOpen}
        email={state.email}
        subscribed={state.subscribed}
        subscribing={state.subscribing}
        error={state.subscribeError}
        onEmail={set.setEmail}
        onSubscribe={actions.subscribe}
        onClose={() => setBetaOpen(false)}
      />

      <Hero
        heroMounted={state.heroMounted}
        heroText1={state.heroText1}
        heroText2={state.heroText2}
        onBeta={() => setBetaOpen(true)}
        ob={ob}
        obPhase={obPhase}
      />

      {/* Everything below the hero steps aside for the choreography. `opacity`
          only — no transform — so no stacking context is created at the idle
          value of 1 and the acts' sticky/fixed machinery is untouched. */}
      <div
        style={{
          opacity: onboarding ? 0 : 1,
          transition: 'opacity 600ms ease',
          pointerEvents: onboarding ? 'none' : 'auto',
        }}
      >
        {/* ═══ Descent band ═══
            Opaque, and exact-colour at both edges: it starts on the flat #F0F4F2
            the hero's legibility band converges to, and ends on the act stage's
            #DCE7DF edge tint. Solid-to-solid joins are the only seams that stay
            invisible — the grounds either side carry washes no flat colour can
            match. */}
        <div
          aria-hidden="true"
          style={{
            position: 'relative', height: '38vh',
            background:
              'linear-gradient(180deg, #F0F4F2 0%, #EDF2EF 35%, #E5EEE8 70%, #DCE7DF 100%)',
          }}
        />

        <ActGraph
          actCanvasRef={actCanvasRef}
          cinemaRef={cinemaRef}
          graph={state.graph}
          exploring={state.exploring}
          expNode={state.expNode}
          onSelectNode={set.setExpNode}
          onExitExplore={actions.exitExplore}
          onQuiz={() => { actions.exitExplore(); setTimeout(() => actions.openGal(0, null), 260); }}
          onLearn={() => { actions.exitExplore(); setTimeout(() => actions.openGal(2, null), 260); }}
        />

        <RiseBand />

        <ActIngest ingestSceneRef={ingestSceneRef} ingestStageRef={ingestStageRef} />

        <ActTutor carouselRef={carouselRef} tutorMode={state.tutorMode} onSetMode={set.setTutorMode} />

        <Gallery trackARef={trackARef} trackBRef={trackBRef} onOpen={actions.openGal} />

        <Faq openFaq={state.openFaq} onToggle={set.setOpenFaq} />

        <Journal
          email={state.email}
          subscribed={state.subscribed}
          subscribing={state.subscribing}
          error={state.subscribeError}
          onEmail={set.setEmail}
          onSubscribe={actions.subscribe}
        />

        <FinalCta onGetStarted={() => setBetaOpen(true)} />

        <SiteFooter />

        <FeatureLab
          index={state.galIdx}
          panelRef={actions.registerPanel}
          onClose={actions.closeGal}
          onPick={(i) => actions.openGal(i, null)}
        />
      </div>

      {/* ═══ Onboarding intro: Let's Learn About You ═══ */}
      {onboarding && (
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
            fontFamily: "var(--font-playfair), 'Playfair Display', Georgia, serif",
            fontSize: 'clamp(26px, 4vw, 50px)',
            fontWeight: 600,
            color: '#0f172a',
            textShadow: '0 1px 2px rgba(255,255,255,0.9)',
            letterSpacing: '-0.02em',
            textAlign: 'center',
            lineHeight: 1.2,
            margin: 0,
          }}>
            Let&apos;s Learn About You...
          </p>
        </div>
      )}

      {/* ═══ Outro: Welcome to Sapling ═══ */}
      {obPhase === 'complete' && (
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
            fontFamily: "var(--font-playfair), 'Playfair Display', Georgia, serif",
            fontSize: 'clamp(30px, 5vw, 62px)',
            fontWeight: 600,
            color: '#0f172a',
            textShadow: '0 1px 2px rgba(255,255,255,0.9)',
            letterSpacing: '-0.025em',
            textAlign: 'center',
            lineHeight: 1.1,
            margin: 0,
          }}>
            Welcome to Sapling
          </p>
        </div>
      )}

      {/* ═══ Outro white overlay — covers the handoff to /dashboard ═══ */}
      <div style={{
        position: 'fixed', inset: 0, zIndex: 92,
        background: 'white',
        opacity: outroOverlay ? 1 : 0,
        transition: 'opacity 900ms cubic-bezier(0.4,0,0.2,1)',
        pointerEvents: 'none',
      }} />

      {/* ═══ Onboarding flow ═══ */}
      {onboarding && (
        <OnboardingFlow
          visible={obPhase === 'active'}
          onClose={closeOnboarding}
          onFinish={handleOnboardingComplete}
          activeStep={obStep}
          completed={obDone}
          setActiveStep={setObStep}
          setCompleted={setObDone}
        />
      )}
    </div>
  );
}
