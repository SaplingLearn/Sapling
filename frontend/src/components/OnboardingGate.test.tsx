// @vitest-environment jsdom
/**
 * Onboarding is enforced in the app shell (owner decision, 2026-11-12): a
 * signed-in student whose GET /api/auth/me says `onboarding_completed: false`
 * is sent to /onboarding and sees no app page. Anything less definite renders
 * the page.
 */
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';

const replace = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ replace }) }));

let ctx: { userReady: boolean; isAuthenticated: boolean; onboardingCompleted: boolean | null | undefined };
vi.mock('@/context/UserContext', () => ({ useUser: () => ctx }));

import { OnboardingGate } from './OnboardingGate';

function renderGate() {
  return render(
    <OnboardingGate>
      <p data-testid="app-page">Dashboard</p>
    </OnboardingGate>,
  );
}

describe('OnboardingGate', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    ctx = { userReady: true, isAuthenticated: true, onboardingCompleted: true };
  });
  afterEach(cleanup);

  it('sends a student who has not finished onboarding there, and shows nothing of the app', () => {
    ctx.onboardingCompleted = false;
    renderGate();
    expect(replace).toHaveBeenCalledWith('/onboarding');
    expect(screen.queryByTestId('app-page')).toBeNull();
  });

  it('lets an onboarded student in', () => {
    renderGate();
    expect(screen.getByTestId('app-page')).toBeTruthy();
    expect(replace).not.toHaveBeenCalled();
  });

  it.each([
    ['not answered yet', { onboardingCompleted: null }],
    ['an older context with no answer at all', { onboardingCompleted: undefined }],
    ['signed out (the middleware owns that)', { isAuthenticated: false, onboardingCompleted: false }],
    ['still loading', { userReady: false, onboardingCompleted: false }],
  ])('renders the page when %s', (_label, patch) => {
    ctx = { ...ctx, ...patch };
    renderGate();
    expect(screen.getByTestId('app-page')).toBeTruthy();
    expect(replace).not.toHaveBeenCalled();
  });

  it('lets the page in as soon as onboarding is marked complete', () => {
    ctx.onboardingCompleted = false;
    const view = renderGate();
    ctx = { ...ctx, onboardingCompleted: true };
    view.rerender(
      <OnboardingGate>
        <p data-testid="app-page">Dashboard</p>
      </OnboardingGate>,
    );
    expect(screen.getByTestId('app-page')).toBeTruthy();
  });
});
