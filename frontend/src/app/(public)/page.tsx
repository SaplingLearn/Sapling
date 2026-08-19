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

import { useCallback, useState, useSyncExternalStore } from 'react';
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
import { galIndexOf } from '@/lib/landing/content';

/**
 * The auth error code the visitor arrived with, e.g. `/?error=session_expired`
 * from `src/middleware.ts` when it bounces an expired session off a protected
 * route, or from the OAuth callback. Without this read the visitor lands on the
 * marketing page with no explanation and `SignInModal`'s entire `ERROR_COPY`
 * table is dead code.
 *
 * Read through `useSyncExternalStore` rather than an effect or
 * `useSearchParams()`, both of which are wrong here:
 *   - an effect that calls setState on mount is what react-hooks/set-state-in-effect
 *     rejects, and it paints one frame of the page without the modal first;
 *   - `useSearchParams()` in a client component at the route root forces the
 *     whole landing to be wrapped in Suspense or rendered dynamically, and a
 *     Suspense hole with a null fallback would prerender an empty marketing page.
 * `getServerSnapshot` returns null so the prerendered HTML matches hydration;
 * React then re-renders with the real value.
 */
function readAuthErrorParam(): string | null {
  return new URLSearchParams(window.location.search).get('error');
}

/**
 * `popstate` covers back/forward. `history.replaceState` (used by
 * `clearAuthErrorParam` below) does NOT fire it, so that helper dispatches a
 * synthetic one — that is how dismissing the modal makes this store re-read.
 */
function subscribeToAuthErrorParam(onChange: () => void): () => void {
  window.addEventListener('popstate', onChange);
  return () => window.removeEventListener('popstate', onChange);
}

function serverAuthErrorParam(): null {
  return null;
}

/**
 * Strip `?error=` and notify the store. Dismissing the modal is therefore also
 * what cleans the URL, so a reload or a copied link doesn't resurrect a stale
 * "your session expired".
 */
function clearAuthErrorParam(): void {
  const params = new URLSearchParams(window.location.search);
  if (!params.has('error')) return;
  params.delete('error');
  const qs = params.toString();
  window.history.replaceState({}, '', window.location.pathname + (qs ? `?${qs}` : ''));
  window.dispatchEvent(new PopStateEvent('popstate'));
}

export default function LandingPage() {
  const {
    rootRef, ambientCanvasRef, navRef, heroCanvasRef, glCanvasRef, heroContentRef,
    actCanvasRef, cinemaRef, ingestSceneRef, ingestStageRef, carouselRef, trackARef, trackBRef,
    state, set, actions,
  } = useLanding({ loadCounter: true });

  // Carried over from the page this replaced: the nav's Sign In still opens
  // the real OAuth modal rather than scrolling somewhere.
  const [signInRequested, setSignInRequested] = useState(false);
  // Added by request. The design scrolls both beta CTAs down to the
  // newsletter section instead; they open this dialog now.
  const [betaOpen, setBetaOpen] = useState(false);

  const signInError = useSyncExternalStore(
    subscribeToAuthErrorParam,
    readAuthErrorParam,
    serverAuthErrorParam,
  );
  // An inbound error code opens the modal on its own — the visitor didn't ask
  // for it, the middleware did, and the message only exists inside the modal.
  const signInOpen = signInRequested || signInError !== null;
  const closeSignIn = useCallback(() => {
    setSignInRequested(false);
    clearAuthErrorParam();
  }, []);

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
        onSignIn={() => setSignInRequested(true)}
        onGetStarted={() => actions.scrollToId('cta')}
      />

      <SignInModal
        open={signInOpen}
        onClose={closeSignIn}
        errorCode={signInError}
      />

      <BetaModal
        open={betaOpen}
        email={state.email}
        subscribed={state.subscribed}
        subscribing={state.subscribing}
        error={state.subscribeError}
        onEmail={set.setEmail}
        onSubscribe={actions.subscribe}
        // state.subscribeError is shared with the Journal form below, and
        // useLanding never clears it. Without this reset a failed attempt in
        // the modal leaves the error rendered in the Journal and shown again
        // the next time the modal opens.
        onClose={() => { setBetaOpen(false); actions.resetSubscribeError(); }}
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
        onQuiz={() => { actions.exitExplore(); setTimeout(() => actions.openGal(galIndexOf('quiz'), null), 260); }}
        onLearn={() => { actions.exitExplore(); setTimeout(() => actions.openGal(galIndexOf('tutor'), null), 260); }}
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
