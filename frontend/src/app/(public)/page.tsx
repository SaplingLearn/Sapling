'use client';

import { useCallback, useEffect, useState } from 'react';
import SignInModal, { type SignInVariant } from '@/components/marketing/SignInModal';
import { useSignInErrorParam, useSignInRequestParam } from '@/components/marketing/useSignInErrorParam';
import { useGetStarted } from '@/components/marketing/useGetStarted';
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
import { useLanding, type ScrambleStep } from '@/components/landing/useLanding';

const HERO_CASCADE: ScrambleStep[] = [
  { slot: 2, text: 'Grow Your Knowledge', durationMs: 1200, delayMs: 200 },
];

export default function LandingPage() {
  const {
    rootRef, ambientCanvasRef, navRef,
    actCanvasRef, cinemaRef, ingestSceneRef, ingestStageRef, carouselRef, trackARef, trackBRef,
    state, set, actions,
  } = useLanding({ loadCounter: true, cascade: HERO_CASCADE });

  // Carried over from the page this replaced: the nav's Sign In still opens
  // the real OAuth modal rather than scrolling somewhere.
  const [signInOpen, setSignInOpen] = useState(false);
  const [signInVariant, setSignInVariant] = useState<SignInVariant>('signin');
  // #756: a failed sign-in lands here as `/?error=<code>`; open the modal
  // with that error's copy (e.g. account_deleted) instead of saying nothing.
  const [signInError, clearSignInError] = useSignInErrorParam();
  // `/?signin=1`: the companion pages' Sign In, or onboarding with no one
  // signed in, asks for the box.
  const [signInAsked, clearSignInAsked] = useSignInRequestParam();
  // Added by request. The design scrolls both beta CTAs down to the
  // newsletter section instead; they open this dialog now.
  const [betaOpen, setBetaOpen] = useState(false);

  const openSignIn = useCallback((variant: SignInVariant) => {
    setSignInVariant(variant);
    setSignInOpen(true);
  }, []);
  // Sign in first (owner decision, 2026-11-12): Get Started opens the sign-in
  // box ("Get started."), and onboarding follows sign-in. A signed-in visitor
  // goes straight to /onboarding or /dashboard.
  const getStarted = useGetStarted(useCallback(() => openSignIn('start'), [openSignIn]));

  // The document scrollbar is hidden while the landing is mounted: the page
  // is a guided scroll cinema and the bar reads as stray chrome against the
  // full-bleed grounds. Scrolling itself is untouched.
  useEffect(() => {
    document.documentElement.classList.add('ld-noscrollbar');
    return () => document.documentElement.classList.remove('ld-noscrollbar');
  }, []);

  // Pinned light: since the graph act moved onto the light ground there is
  // no full-bleed dark section left for the bar to invert over. The dark
  // table and the scroll rule live on in navTheme.ts if one returns.
  const navTheme = NAV_LIGHT;

  return (
    <div
      ref={rootRef}
      className="landing-dc landing-v5"
      style={{
        fontFamily: "var(--font-suse), 'SUSE', system-ui, sans-serif", color: '#191F13', fontSize: 14,
        lineHeight: 1.6, backgroundColor: '#f2f4f0',
        backgroundImage:
          'radial-gradient(ellipse 100% 60% at 50% -10%, rgba(255,255,255,0.55) 0%, transparent 50%), radial-gradient(ellipse 80% 50% at 100% 40%, rgba(255,255,255,0.2) 0%, transparent 45%)',
        minHeight: '100vh', overflowX: 'clip',
      }}
    >
      {/* ambient constellation, behind everything */}
      <canvas
        ref={ambientCanvasRef}
        aria-hidden="true"
        style={{
          position: 'fixed', inset: 0, zIndex: -1, width: '100%', height: '100%',
          pointerEvents: 'none',
        }}
      />

      <IntroOverlay
        heroMounted={state.heroMounted}
        introGone={state.introGone}
        loadPct={state.loadPct}
      />

      <Navbar
        navRef={navRef}
        heroMounted={state.heroMounted}
        exploring={state.exploring}
        theme={navTheme}
        onLogoClick={actions.scrollTop}
        onSignIn={() => openSignIn('signin')}
        onGetStarted={() => void getStarted()}
      />

      <SignInModal
        open={signInOpen || signInError !== null || signInAsked}
        onClose={() => {
          setSignInOpen(false);
          clearSignInError();
          clearSignInAsked();
        }}
        errorCode={signInError}
        variant={signInVariant}
      />

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
        heroText2={state.heroText2}
        onBeta={() => setBetaOpen(true)}
      />

      {/* ═══ Descent band ═══
          Opaque, and exact-colour at both edges: it starts on the flat #F2F4F0
          the hero's legibility band converges to, and ends on the act stage's
          #E0E6DB edge tint. Solid-to-solid joins are the only seams that stay
          invisible — the grounds either side carry washes no flat colour can
          match. */}
      <div
        aria-hidden="true"
        style={{
          position: 'relative', height: '38vh',
          background:
            'linear-gradient(180deg, #F2F4F0 0%, #EFF1ED 35%, #E9EDE4 70%, #E0E6DB 100%)',
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
  );
}
