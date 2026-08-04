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
import { Hero } from '@/components/landing-v5/Hero';
import { IntroOverlay } from '@/components/landing-v5/IntroOverlay';
import { Navbar } from '@/components/landing-v5/Navbar';
import { NAV_DARK, NAV_LIGHT, useNavDark } from '@/components/landing-v5/navTheme';
import { useLanding } from '@/components/landing/useLanding';

export default function LandingPage() {
  const {
    rootRef, ambientCanvasRef, navRef, heroCanvasRef, glCanvasRef, heroContentRef,
    state, set, actions,
  } = useLanding({ loadCounter: true });

  // Carried over from the page this replaced: the nav's Sign In still opens
  // the real OAuth modal rather than scrolling somewhere.
  const [signInOpen, setSignInOpen] = useState(false);

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

      <Hero
        heroCanvasRef={heroCanvasRef}
        glCanvasRef={glCanvasRef}
        heroContentRef={heroContentRef}
        heroText0={state.heroText0}
        heroText1={state.heroText1}
        onBeta={() => actions.scrollToId('newsletter')}
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
    </div>
  );
}
