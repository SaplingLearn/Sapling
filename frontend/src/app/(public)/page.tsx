'use client';

/**
 * The Sapling landing page.
 *
 * Ported from `Sapling Landing v5.dc.html`. This is the page at `/` — it
 * replaced the previous marketing landing outright rather than sitting
 * beside it.
 *
 * Sections land incrementally; the engine drives whatever is mounted.
 */

import { useState } from 'react';
import SignInModal from '@/components/marketing/SignInModal';
import { ActGraph, RiseBand } from '@/components/landing-v5/ActGraph';
import { ActIngest } from '@/components/landing-v5/ActIngest';
import { BetaModal } from '@/components/landing-v5/BetaModal';
import { ActTutor } from '@/components/landing-v5/ActTutor';
import { FinalCta, SectionNav, SiteFooter } from '@/components/landing-v5/Closing';
import { Faq } from '@/components/landing-v5/Faq';
import { FeatureLab } from '@/components/landing-v5/FeatureLab';
import { Journal } from '@/components/landing-v5/Journal';
import { Gallery } from '@/components/landing-v5/Gallery';
import { Hero } from '@/components/landing-v5/Hero';
import { IntroOverlay } from '@/components/landing-v5/IntroOverlay';
import { Navbar } from '@/components/landing-v5/Navbar';
import { NAV_DARK, NAV_LIGHT, useNavDark } from '@/components/landing-v5/navTheme';
import { useLanding } from '@/components/landing/useLanding';

export default function LandingPage() {
  const {
    rootRef, ambientCanvasRef, navRef, heroCanvasRef, glCanvasRef, heroContentRef,
    actCanvasRef, cinemaRef, ingestSceneRef, ingestStageRef, carouselRef, trackARef, trackBRef,
    state, set, actions,
  } = useLanding({ loadCounter: true });

  // Carried over from the page this replaced: the nav's Sign In still opens
  // the real OAuth modal rather than scrolling somewhere.
  const [signInOpen, setSignInOpen] = useState(false);
  // Added by request. The design scrolls both beta CTAs down to the
  // newsletter section instead; they open this dialog now.
  const [betaOpen, setBetaOpen] = useState(false);

  // The source builds this table then pins it to light with `wantDark = false`.
  // Driven for real here — see navTheme.ts.
  const navTheme = useNavDark() ? NAV_DARK : NAV_LIGHT;

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
        navMenuOpen={state.navMenuOpen}
        theme={navTheme}
        onToggleMenu={() => set.setNavMenuOpen(!state.navMenuOpen)}
        onCloseMenu={() => set.setNavMenuOpen(false)}
        onLogoClick={actions.scrollTop}
        onSignIn={() => setSignInOpen(true)}
        onGetStarted={() => actions.scrollToId('cta')}
      />

      <SignInModal open={signInOpen} onClose={() => setSignInOpen(false)} />

      <BetaModal
        open={betaOpen}
        email={state.email}
        subscribed={state.subscribed}
        onEmail={set.setEmail}
        onSubscribe={actions.subscribe}
        onClose={() => setBetaOpen(false)}
      />

      <Hero
        heroCanvasRef={heroCanvasRef}
        glCanvasRef={glCanvasRef}
        heroContentRef={heroContentRef}
        heroText0={state.heroText0}
        heroText1={state.heroText1}
        onBeta={() => setBetaOpen(true)}
        onSeeHow={() => actions.scrollToId('gallery')}
      />

      {/* ═══ Descent band ═══ */}
      <div
        aria-hidden="true"
        style={{
          position: 'relative', height: '38vh',
          background:
            'linear-gradient(180deg, #F0F4F2 0%, #E4EEE7 10%, #CFE2D5 22%, #A8C9B5 34%, #74A288 46%, #46765C 58%, #2A5A40 68%, #143725 78%, #0A2417 87%, #081F14 94%, #081F14 100%)',
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
        onEmail={set.setEmail}
        onSubscribe={actions.subscribe}
      />

      <FinalCta onGetStarted={() => setBetaOpen(true)} />

      <SiteFooter />

      <SectionNav
        open={state.jumpOpen}
        onToggle={() => set.setJumpOpen(!state.jumpOpen)}
        onJump={actions.scrollToId}
        onTop={actions.scrollTop}
      />

      <FeatureLab
        index={state.galIdx}
        panelRef={actions.registerPanel}
        onClose={actions.closeGal}
        onPick={(i) => actions.openGal(i, null)}
      />
    </div>
  );
}
