'use client';

import { useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { useUser } from '@/context/UserContext';
import { getMe } from '@/lib/api';
import { postSignInRoute } from '@/lib/localSeed';

/**
 * The landing's Get Started (owner decision, 2026-11-12: sign in first).
 *
 * Signed out, it opens the sign-in box; onboarding starts after sign-in, by
 * the same routing every sign-in takes. Signed in, it goes where that routing
 * would: /pending for an account that isn't let in yet, otherwise /onboarding
 * or /dashboard by the account's `onboarding_completed` (postSignInRoute,
 * which also keeps a new local account on its sample-data hold screen). The
 * answer is read fresh from GET /api/auth/me; a session that turns out to be
 * dead (or can't be checked) opens the sign-in box instead.
 */
export function useGetStarted(openSignIn: () => void): () => Promise<void> {
  const router = useRouter();
  const { isAuthenticated } = useUser();

  return useCallback(async () => {
    if (!isAuthenticated) {
      openSignIn();
      return;
    }
    try {
      const me = await getMe();
      router.push(me.is_approved ? await postSignInRoute(!!me.onboarding_completed) : '/pending');
    } catch {
      openSignIn();
    }
  }, [isAuthenticated, openSignIn, router]);
}
