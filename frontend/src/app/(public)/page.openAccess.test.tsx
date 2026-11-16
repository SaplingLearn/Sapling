// @vitest-environment jsdom
/**
 * The landing's beta CTAs follow the waitlist gate
 * (docs/design/open-access-gate.md): with `open_access` on they say "Sign up"
 * and open the sign-in box ("Get started."); otherwise they say "Sign up for
 * Beta Testing" and open the waitlist dialog.
 */
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));
vi.mock('@/context/UserContext', () => ({
  useUser: () => ({ isAuthenticated: false, userReady: true, setActiveUser: vi.fn() }),
}));

let openAccess = false;
vi.mock('@/lib/openAccess', () => ({ useOpenAccess: () => openAccess }));

const ref = () => ({ current: null });
vi.mock('@/components/landing/useLanding', () => ({
  useLanding: () => ({
    rootRef: ref(), ambientCanvasRef: ref(), navRef: ref(), actCanvasRef: ref(), cinemaRef: ref(),
    ingestSceneRef: ref(), ingestStageRef: ref(), carouselRef: ref(), trackARef: ref(), trackBRef: ref(),
    state: {
      heroMounted: true, heroText2: '', loadPct: 100, introGone: true, graph: null, tutorMode: 'socratic',
      galIdx: null, exploring: false, expNode: null, openFaq: null, email: '', subscribed: false,
      subscribing: false, subscribeError: null,
    },
    set: { setExpNode: vi.fn(), setTutorMode: vi.fn(), setOpenFaq: vi.fn(), setEmail: vi.fn() },
    actions: {
      scrollTop: vi.fn(), exitExplore: vi.fn(), openGal: vi.fn(), closeGal: vi.fn(),
      registerPanel: vi.fn(), subscribe: vi.fn(),
    },
  }),
}));

type Cta = { onBeta?: () => void; onGetStarted?: () => void; ctaLabel?: string };
const Stub = vi.hoisted(() => () => null);
vi.mock('@/components/landing-v5/Hero', () => ({
  Hero: ({ onBeta, ctaLabel }: Cta) => <button data-testid="hero-cta" onClick={onBeta}>{ctaLabel}</button>,
}));
vi.mock('@/components/landing-v5/Closing', () => ({
  FinalCta: ({ onGetStarted, ctaLabel }: Cta) => (
    <button data-testid="final-cta" onClick={onGetStarted}>{ctaLabel}</button>
  ),
  SiteFooter: Stub,
}));
vi.mock('@/components/landing-v5/BetaModal', () => ({
  BetaModal: ({ open }: { open: boolean }) => (open ? <div data-testid="beta-modal" /> : null),
}));
vi.mock('@/components/landing-v5/ActGraph', () => ({ ActGraph: Stub, RiseBand: Stub }));
vi.mock('@/components/landing-v5/ActIngest', () => ({ ActIngest: Stub }));
vi.mock('@/components/landing-v5/ActTutor', () => ({ ActTutor: Stub }));
vi.mock('@/components/landing-v5/Faq', () => ({ Faq: Stub }));
vi.mock('@/components/landing-v5/FeatureLab', () => ({ FeatureLab: Stub }));
vi.mock('@/components/landing-v5/Journal', () => ({ Journal: Stub }));
vi.mock('@/components/landing-v5/Gallery', () => ({ Gallery: Stub }));
vi.mock('@/components/landing-v5/IntroOverlay', () => ({ IntroOverlay: Stub }));

import LandingPage from './page';

describe('the landing beta CTAs and open access', () => {
  beforeEach(() => {
    openAccess = false;
    window.history.replaceState({}, '', '/');
  });
  afterEach(cleanup);

  it.each(['hero-cta', 'final-cta'])('waitlist required: %s offers the waitlist dialog', async (id) => {
    render(<LandingPage />);
    const cta = screen.getByTestId(id);
    expect(cta.textContent).toBe('Sign up for Beta Testing');
    fireEvent.click(cta);
    expect(await screen.findByTestId('beta-modal')).toBeTruthy();
    expect(screen.queryByTestId('signin-modal')).toBeNull();
  });

  it.each(['hero-cta', 'final-cta'])('open access: %s says Sign up and opens sign-in', async (id) => {
    openAccess = true;
    render(<LandingPage />);
    const cta = screen.getByTestId(id);
    expect(cta.textContent).toBe('Sign up');
    fireEvent.click(cta);
    expect((await screen.findByTestId('signin-title')).textContent).toBe('Get started.');
    expect(screen.queryByTestId('beta-modal')).toBeNull();
  });
});
