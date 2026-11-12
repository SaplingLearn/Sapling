// @vitest-environment jsdom
/**
 * The landing's Get Started and Sign In (sign in first, 2026-11-12). Get
 * Started no longer plays onboarding over the landing: signed out it opens
 * the sign-in box titled "Get started."; signed in it goes where sign-in
 * would, by the account's approval and onboarding state. The animated acts
 * are stubbed: only the navbar and the sign-in box are real here.
 */
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

const push = vi.fn();
const replace = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace }) }));

let authed = false;
vi.mock('@/context/UserContext', () => ({
  useUser: () => ({ isAuthenticated: authed, userReady: true, setActiveUser: vi.fn() }),
}));

const getMe = vi.fn();
vi.mock('@/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api')>()),
  getMe: () => getMe(),
}));

const postSignInRoute = vi.fn(async (onboarded: boolean) => (onboarded ? '/dashboard' : '/onboarding'));
vi.mock('@/lib/localSeed', () => ({ postSignInRoute: (o: boolean) => postSignInRoute(o) }));

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
const Stub = vi.hoisted(() => () => null);
vi.mock('@/components/landing-v5/ActGraph', () => ({ ActGraph: Stub, RiseBand: Stub }));
vi.mock('@/components/landing-v5/ActIngest', () => ({ ActIngest: Stub }));
vi.mock('@/components/landing-v5/BetaModal', () => ({ BetaModal: Stub }));
vi.mock('@/components/landing-v5/ActTutor', () => ({ ActTutor: Stub }));
vi.mock('@/components/landing-v5/Closing', () => ({ FinalCta: Stub, SiteFooter: Stub }));
vi.mock('@/components/landing-v5/Faq', () => ({ Faq: Stub }));
vi.mock('@/components/landing-v5/FeatureLab', () => ({ FeatureLab: Stub }));
vi.mock('@/components/landing-v5/Journal', () => ({ Journal: Stub }));
vi.mock('@/components/landing-v5/Gallery', () => ({ Gallery: Stub }));
vi.mock('@/components/landing-v5/Hero', () => ({ Hero: Stub }));
vi.mock('@/components/landing-v5/IntroOverlay', () => ({ IntroOverlay: Stub }));

import LandingPage from './page';
import { ApiError } from '@/lib/api';

describe('the landing page: Sign In and Get Started', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authed = false;
    window.history.replaceState({}, '', '/');
  });
  afterEach(cleanup);

  it('Get Started, signed out, opens the sign-in box as "Get started." and plays no onboarding', async () => {
    render(<LandingPage />);
    fireEvent.click(screen.getByTestId('landing-get-started'));
    expect((await screen.findByTestId('signin-title')).textContent).toBe('Get started.');
    expect(screen.queryByTestId('onboarding-gate')).toBeNull();
    expect(screen.queryByTestId('onboarding-takeover')).toBeNull();
    expect(getMe).not.toHaveBeenCalled();
    expect(push).not.toHaveBeenCalled();
  });

  it('Sign In opens the box as "Welcome back."', async () => {
    render(<LandingPage />);
    fireEvent.click(screen.getByTestId('signin-trigger'));
    expect((await screen.findByTestId('signin-title')).textContent).toBe('Welcome back.');
  });

  it.each([
    ['has not finished onboarding', { is_approved: true, onboarding_completed: false }, '/onboarding'],
    ['has finished onboarding', { is_approved: true, onboarding_completed: true }, '/dashboard'],
    ['is not approved yet', { is_approved: false, onboarding_completed: false }, '/pending'],
  ])('Get Started, signed in, for an account that %s goes to %s', async (_label, me, route) => {
    authed = true;
    getMe.mockResolvedValueOnce({ user_id: 'u1', name: 'Ada', ...me });
    render(<LandingPage />);
    fireEvent.click(screen.getByTestId('landing-get-started'));
    await waitFor(() => expect(push).toHaveBeenCalledWith(route));
    expect(screen.queryByTestId('signin-modal')).toBeNull();
  });

  it('Get Started on a session that turns out dead opens the sign-in box instead', async () => {
    authed = true;
    getMe.mockRejectedValueOnce(new ApiError('{"detail":"Not authenticated"}', 401));
    render(<LandingPage />);
    await act(async () => { fireEvent.click(screen.getByTestId('landing-get-started')); });
    expect((await screen.findByTestId('signin-title')).textContent).toBe('Get started.');
    expect(push).not.toHaveBeenCalled();
  });

  it('/?signin=1 opens the sign-in box (the companion pages\' Sign In, onboarding signed out)', async () => {
    window.history.replaceState({}, '', '/?signin=1');
    render(<LandingPage />);
    expect((await screen.findByTestId('signin-title')).textContent).toBe('Welcome back.');
    expect(window.location.search).toBe('');
  });

  it('/?error=cancelled opens the box with the reason', async () => {
    window.history.replaceState({}, '', '/?error=cancelled');
    render(<LandingPage />);
    expect((await screen.findByTestId('signin-error')).textContent).toBe('Sign-in was cancelled.');
  });
});
