'use client';

/**
 * Sapling Landing v4 — scroll-driven cinematic landing page.
 *
 * Ported from `Sapling Landing v4.dc.html`. Lives on its own route while it
 * is built out, so the existing landing at `/` keeps working and the two can
 * be compared side by side.
 *
 * Sections land incrementally; the engine drives whatever is mounted.
 */

import { Hero } from '@/components/landing-v4/Hero';
import { IntroOverlay } from '@/components/landing-v4/IntroOverlay';
import { Navbar } from '@/components/landing-v4/Navbar';
import { useLandingV4 } from '@/components/landing-v4/useLandingV4';

export default function LandingV4Page() {
  const {
    rootRef, ambientCanvasRef, navRef, heroCanvasRef, heroContentRef,
    state, set, actions,
  } = useLandingV4({});

  return (
    <div
      ref={rootRef}
      className="landing-v4"
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

      <IntroOverlay heroMounted={state.heroMounted} />

      <Navbar
        navRef={navRef}
        heroMounted={state.heroMounted}
        exploring={state.exploring}
        navMenuOpen={state.navMenuOpen}
        onToggleMenu={() => set.setNavMenuOpen(!state.navMenuOpen)}
        onCloseMenu={() => set.setNavMenuOpen(false)}
        onLogoClick={actions.scrollTop}
        onGetStarted={() => actions.scrollToId('cta')}
      />

      <Hero
        heroCanvasRef={heroCanvasRef}
        heroContentRef={heroContentRef}
        heroMounted={state.heroMounted}
        heroText1={state.heroText1}
        heroText2={state.heroText2}
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
