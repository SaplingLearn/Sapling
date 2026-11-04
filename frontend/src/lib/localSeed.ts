/**
 * #715: post-sign-in routing for a developer's local stack.
 *
 * A local backend copies the rich sample dataset onto each Google account
 * that signs in (backend services/local_seed_watcher.py), so a NEW account
 * should wait on the hold screen instead of landing on an empty /onboarding.
 * GET /api/auth/local-seed 404s on every non-local backend, and any failure
 * to ask falls back to /onboarding, so outside local the routing is exactly
 * what it was. Shared by the same-tab callback and the popup sign-in modal.
 */
import { getLocalSeedStatus } from '@/lib/api';

export const SETUP_ROUTE = '/setting-up';

export async function postSignInRoute(onboardingCompleted: boolean): Promise<string> {
  if (onboardingCompleted) return '/dashboard';
  try {
    const { state } = await getLocalSeedStatus();
    if (state === 'ready') return '/dashboard';
    if (state === 'pending' || state === 'seeding' || state === 'failed') return SETUP_ROUTE;
  } catch {
    // 404 (not a local backend), 401, network: today's behaviour.
  }
  return '/onboarding';
}

/**
 * Where /onboarding should send a local account instead, or null to stay.
 * Covers every way past postSignInRoute (a tab running older code, a dev-server
 * reload mid-sign-in, a typed URL). A failed seed stays, because that is where
 * the hold screen's "Continue anyway" points.
 */
export async function onboardingRedirect(): Promise<string | null> {
  try {
    const { state } = await getLocalSeedStatus();
    if (state === 'pending' || state === 'seeding' || state === 'ready') return SETUP_ROUTE;
  } catch {
    // 404 (not a local backend), 401, network: stay on onboarding.
  }
  return null;
}
