'use client';

import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  useMemo,
  useCallback,
  useSyncExternalStore,
} from 'react';
import type { UserRole, EquippedCosmetics, Role } from '@/lib/types';
import { usePathname } from 'next/navigation';
import { API_URL, getMe, onSessionExpired } from '@/lib/api';
import { readAccountSettings } from '@/lib/accountSettings';
import { isAppShellRoute } from '@/lib/appRoutes';
import { clearUserScopedStorage } from '@/lib/userScopedStorage';
import { purgeGuestOnboardingDraft } from '@/lib/onboardingDraft';
import { cacheBustedAvatar, isDeadSessionStatus, profileFields } from './userProfile';
import {
  ACCOUNT_REFRESH_MS,
  accountRefreshDue,
  needsAccountRead,
  pageviewsMayRun,
  resumeAnalytics,
  stopAnalytics,
  subscribeAnalytics,
} from '@/lib/analytics';

const pageviewsNeverRunOnServer = () => false;

interface UserContextValue {
  userId: string;
  userName: string;
  avatarUrl: string;
  userReady: boolean;
  isAuthenticated: boolean;
  username: string | null;
  roles: UserRole[];
  equippedCosmetics: EquippedCosmetics;
  featuredRole: Role | null;
  isAdmin: boolean;
  setActiveUser: (id: string, name: string, avatar?: string, opts?: { persist?: boolean }) => void;
  signOut: () => Promise<void>;
  refreshProfile: () => Promise<void>;
  /**
   * GET /api/auth/me's `onboarding_completed` for this account; null until it
   * has answered (and after an account change). The shell sends a student
   * whose answer is `false` to /onboarding (components/OnboardingGate.tsx).
   */
  onboardingCompleted: boolean | null;
  /** The onboarding save just finished (or found it already finished): the
   * shell may let this account in without waiting for the next /me. */
  markOnboarded: () => void;
  // Direct setter exposed so callers can do an optimistic UI update
  // (e.g. show a local blob URL for an avatar the user just picked
  // before the upload finishes). The next refreshProfile() will
  // overwrite this with the canonical Supabase URL + cache-bust.
  setAvatarUrl: (url: string) => void;
}

export const UserContext = createContext<UserContextValue>({
  userId: '',
  userName: '',
  avatarUrl: '',
  userReady: false,
  isAuthenticated: false,
  username: null,
  roles: [],
  equippedCosmetics: {},
  featuredRole: null,
  isAdmin: false,
  setActiveUser: () => {},
  signOut: () => Promise.resolve(),
  refreshProfile: () => Promise.resolve(),
  onboardingCompleted: null,
  markOnboarded: () => {},
  setAvatarUrl: () => {},
});

// Pure + exported for tests (window.location is unstubbable under jsdom).
// The shell routes (lib/appRoutes.ts) are where a cleared session leaves no
// usable UI.
export function shouldBounceToSignin(pathname: string): boolean {
  return isAppShellRoute(pathname);
}

/** The account id persisted in `sapling_user`, or '' (none / unreadable). */
function persistedIdentity(): string {
  try {
    const saved = JSON.parse(localStorage.getItem('sapling_user') ?? 'null');
    return saved && typeof saved.id === 'string' ? saved.id : '';
  } catch {
    return '';
  }
}

/**
 * Write a display name /me just confirmed through to `sapling_user`, so the
 * next page load boots with it — only onto this account's own copy, and only
 * when it changed. An unreadable or unwritable copy is left as it is.
 */
function persistConfirmedName(uid: string, name: string): void {
  try {
    const saved = JSON.parse(localStorage.getItem('sapling_user') ?? 'null');
    if (saved && saved.id === uid && saved.name !== name) {
      localStorage.setItem('sapling_user', JSON.stringify({ ...saved, name }));
    }
  } catch {}
}

/** On an auth-flow route (`/auth/*`), which owns its own identity bootstrap. */
function onAuthFlowRoute(): boolean {
  return typeof window !== 'undefined' && window.location.pathname.startsWith('/auth');
}

/**
 * After a cleared session: on a shell route there is no usable UI left
 * (every screen gates on userId) and the next server navigation would be
 * bounced by the middleware anyway — bounce now, with the same greppable
 * code the middleware uses.
 */
function bounceToSigninFromShell(): void {
  if (typeof window !== 'undefined' && shouldBounceToSignin(window.location.pathname)) {
    window.location.replace('/?error=session_expired');
  }
}

export function UserProvider({ children }: { children: React.ReactNode }) {
  const [userId, setUserId] = useState('');
  const [userName, setUserName] = useState('');
  const [avatarUrl, setAvatarUrl] = useState('');
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [userReady, setUserReady] = useState(false);

  const [username, setUsername] = useState<string | null>(null);
  const [roles, setRoles] = useState<UserRole[]>([]);
  const [equippedCosmetics, setEquippedCosmetics] = useState<EquippedCosmetics>({});
  const [featuredRole, setFeaturedRole] = useState<Role | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);
  const [onboardingCompleted, setOnboardingCompleted] = useState<boolean | null>(null);
  // Account changes and newer profile loads invalidate older responses,
  // including a 401 or a body that finishes after sign-out.
  const profileGeneration = React.useRef(0);
  const activeIdentity = React.useRef('');

  const setActiveUser = useCallback((id: string, name: string, avatar?: string, opts?: { persist?: boolean }) => {
    // #756: signing in as someone else on this browser (no sign-out between)
    // must not inherit the previous student's semester, drafts, quiz or
    // privacy toggle. Same account again → nothing is cleared.
    const persisted = persistedIdentity();
    if (
      (activeIdentity.current && activeIdentity.current !== id) ||
      (persisted && persisted !== id)
    ) {
      clearUserScopedStorage();
    }
    // A repeated confirmation of the same account must not cancel its
    // profile load: userId would be unchanged, so the effect would not retry.
    if (id !== activeIdentity.current) {
      profileGeneration.current += 1;
      // Another account's onboarding answer says nothing about this one.
      setOnboardingCompleted(null);
    }
    activeIdentity.current = id;
    setUserId(id);
    setUserName(name);
    if (avatar) setAvatarUrl(avatar);
    setIsAuthenticated(true);
    // #191: persist only an identity confirmed against the live session.
    // Callers pass { persist: false } when GET /api/auth/me could not
    // confirm — the tab still works, and the next full load reconciles via
    // the cookie fallback below instead of trusting a stale localStorage copy.
    if (opts?.persist !== false) {
      localStorage.setItem('sapling_user', JSON.stringify({ id, name, avatar: avatar || '' }));
    }
  }, []);

  useEffect(() => {
    // Onboarding needs an account now (sign in first): drop any answers the
    // old signed-out "guest" onboarding left on this browser.
    purgeGuestOnboardingDraft();
    const saved = localStorage.getItem('sapling_user');
    if (saved) {
      try {
        const { id, name, avatar } = JSON.parse(saved);
        activeIdentity.current = id;
        setUserId(id);
        setUserName(name);
        if (avatar) setAvatarUrl(avatar);
        setIsAuthenticated(true);
      } catch {}
      setUserReady(true);
      return;
    }

    // No `sapling_user` in localStorage — but the HttpOnly `sapling_session`
    // cookie can outlive it (cleared site data, a different browser profile,
    // a stale-cookie flow): middleware already admits the request on the
    // cookie alone, and this context has no client-readable way to see it,
    // so without a fallback userId never gets set and every screen gated on
    // `userReady && userId` (e.g. Dashboard's load effect) waits forever on
    // its loading skeleton (#430). Fall back to the cookie-identified
    // GET /api/auth/me — the same endpoint the OAuth callback
    // (src/app/auth/callback/page.tsx) already reads off the same cookie,
    // though the callback calls it via a bare `fetch`, not this `fetchJSON`
    // wrapper.
    //
    // Skip this fallback entirely on the auth-flow routes (`/auth/*`, e.g.
    // the callback page): the callback POSTs /api/auth/session to mint the
    // cookie and only THEN calls GET /api/auth/me itself before its own
    // setActiveUser. Racing our own getMe() here would be a near-guaranteed
    // 401 before that POST resolves, and — on a shared browser where a
    // DIFFERENT user's still-valid `sapling_session` cookie is present —
    // could momentarily hydrate the wrong identity before the callback's
    // setActiveUser overwrites it moments later. Let the callback own its
    // own bootstrap.
    if (typeof window !== 'undefined' && window.location.pathname.startsWith('/auth')) {
      setUserReady(true);
      return;
    }

    let cancelled = false;
    const generation = profileGeneration.current;
    (async () => {
      try {
        const me = await getMe();
        if (cancelled || generation !== profileGeneration.current) return;
        // Write-through setActiveUser: hydrates state AND persists
        // localStorage, so the next bootstrap takes the fast synchronous
        // path above instead of hitting the network again.
        setActiveUser(me.user_id, me.name || '', me.avatar_url || '');
        if (typeof me.onboarding_completed === 'boolean') setOnboardingCompleted(me.onboarding_completed);
      } catch {
        // No identity source is left, for any reason: a 401 (no/expired
        // session), a 404 (the cookie names a user row that no longer
        // exists — the #285-family stale-session scenario), or a plain
        // network failure. Settle into the existing signed-out state
        // (isAuthenticated stays false); every consumer already gates on
        // `userReady`, so nothing new to redirect here.
        //
        // This also means every anonymous visit to a public page pays for
        // one 401-destined getMe() call here (UserProvider wraps the whole
        // app, public routes included) — the HttpOnly cookie can't be
        // probed client-side without a network round trip, and there's no
        // existing non-HttpOnly signed-in hint to gate on instead. One
        // cheap failed request per anonymous mount is the accepted cost of
        // fixing #430.
      } finally {
        if (!cancelled) setUserReady(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [setActiveUser]);

  // Shared teardown for "this client's identity is no longer valid": local
  // state plus the persisted localStorage copy. Used by signOut and by the
  // #191 stale-identity reconciliation in fetchProfileData.
  const clearStaleClientAuth = useCallback(() => {
    profileGeneration.current += 1;
    activeIdentity.current = '';
    setUserId('');
    setUserName('');
    setAvatarUrl('');
    setIsAuthenticated(false);
    setUsername(null);
    setRoles([]);
    setEquippedCosmetics({});
    setFeaturedRole(null);
    setIsAdmin(false);
    setOnboardingCompleted(null);
    // #756: every user-scoped key, not just the identity — a shared browser
    // must not hand the next student this one's semester, drafts or quiz.
    clearUserScopedStorage();
    // Sign-out, account deletion (Settings → signOut) and a dead session all
    // land here: analytics stops at once, and stopAnalytics resets the
    // PostHog identity, so nothing more is attributed to this account (a
    // soft-deleted one included). No-op when analytics is off.
    stopAnalytics();
  }, []);

  // Product-analytics pageviews (src/lib/analytics.ts) run only for a
  // signed-in student, only inside the app shell (lib/appRoutes.ts — never
  // public or marketing pages, /auth/*, onboarding), and only once their
  // account preference (user_settings.analytics_opt_out) has been read as
  // `false`. Nothing about it is stored in the browser, so it is read on the
  // first shell page of each page load — and only while pageviews may run
  // here at all (pageviewsMayRun: a configured build, the admin
  // `product_analytics` flag on, no DNT/GPC). A build without analytics, or a
  // student the flag is off for, costs no settings request. The read goes
  // through lib/accountSettings.ts, which shares one in-flight GET with the
  // Settings screen and feeds every answer — whoever asked — into the
  // analytics state, so the two never disagree.
  //
  // Signed out → off. A failed read → off, retried on each later shell
  // navigation until it answers or MAX_ACCOUNT_READ_FAILURES reads have
  // failed (needsAccountRead) — bounded, never a loop; opening Settings
  // always reads again. A read overtaken by a Settings toggle or a sign-out
  // is ignored (analytics.ts's generation counter). The capture gate itself
  // also checks the live route, so leaving the shell (Settings → /privacy)
  // stops capture for that page at once.
  const pathname = usePathname();
  const onAppRoute = isAppShellRoute(pathname);
  const mayRun = useSyncExternalStore(subscribeAnalytics, pageviewsMayRun, pageviewsNeverRunOnServer);
  useEffect(() => {
    if (!userReady) return;
    if (!isAuthenticated || !userId) {
      stopAnalytics();
      return;
    }
    // Back in the shell with the answer known: start posthog-js if it is not
    // running (one retry of a failed load per entry into the shell).
    if (mayRun && onAppRoute && !needsAccountRead(userId)) resumeAnalytics();
  }, [userReady, isAuthenticated, userId, onAppRoute, mayRun]);
  useEffect(() => {
    if (!userReady || !isAuthenticated || !userId || !mayRun || !onAppRoute) return;
    if (!needsAccountRead(userId)) return;
    readAccountSettings(userId).catch(() => {
      // Fail closed: analytics.ts records the failure (`unreadable`); the
      // next shell navigation (`pathname`) retries, within the budget.
    });
  }, [userReady, isAuthenticated, userId, onAppRoute, mayRun, pathname]);
  // While this tab is SENDING, re-read the preference every
  // ACCOUNT_REFRESH_MS (visible tabs only) and on coming back to the tab, so
  // an opt-out made on another device or tab stops these pageviews within
  // about a minute without a reload. A failed re-read is `unreadable`: off
  // (fail closed) until a later read answers.
  useEffect(() => {
    if (!userReady || !isAuthenticated || !userId || !mayRun || !onAppRoute) return;
    const tick = () => {
      if (document.visibilityState !== 'visible' || !accountRefreshDue(userId)) return;
      readAccountSettings(userId).catch(() => {
        // Recorded by analytics.ts (`unreadable`); capture is off meanwhile.
      });
    };
    const timer = window.setInterval(tick, ACCOUNT_REFRESH_MS);
    document.addEventListener('visibilitychange', tick);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', tick);
    };
  }, [userReady, isAuthenticated, userId, onAppRoute, mayRun]);

  const fetchProfileData = useCallback(async (uid: string) => {
    if (!uid) return;
    const generation = ++profileGeneration.current;
    try {
      const res = await fetch(`${API_URL}/api/auth/me?user_id=${encodeURIComponent(uid)}`, { credentials: 'include' });
      if (generation !== profileGeneration.current) return;
      if (!res.ok) {
        // #191: a definitive 401/404 means the identity this client holds is
        // dead: clear it so isAuthenticated stops asserting a session the
        // server won't honor. This effect already runs on every authed
        // mount, so the stale-localStorage case self-heals with no extra
        // request. Transient failures (5xx, network) fall through and keep
        // the session — a server blip must not sign the user out.
        if (isDeadSessionStatus(res.status)) {
          clearStaleClientAuth();
          bounceToSigninFromShell();
        }
        return;
      }
      const data = await res.json();
      if (generation !== profileGeneration.current) return;
      // /me answers for whoever owns the session cookie and ignores
      // ?user_id=. A different user_id means this client's identity (e.g. a
      // localStorage copy from another account on a shared browser) is not
      // the session's. The live session is the source of truth, so the tab
      // adopts it: clearing alone left a signed-out tab over a valid cookie
      // that nothing re-bootstraps off the shell routes. The old identity's
      // profile fields are dropped first, and the userId change refetches
      // the adopted one's. A response that lost a race to an account switch
      // or sign-out never gets here (the generation checks above).
      if (data.user_id && data.user_id !== uid) {
        clearStaleClientAuth();
        // The auth-flow routes own their own bootstrap (see the cookie
        // fallback above): just drop the stale identity there.
        if (onAuthFlowRoute()) return;
        setActiveUser(data.user_id, data.name || '', data.avatar_url || '');
        return;
      }
      // /me is the source of truth for the display name (it may have changed
      // since this browser signed in, e.g. from another device). Persist the
      // confirmed name so the next page load boots with it.
      if (data.name) {
        setUserName(data.name);
        persistConfirmedName(uid, data.name);
      }
      if (typeof data.onboarding_completed === 'boolean') setOnboardingCompleted(data.onboarding_completed);
      const profile = profileFields(data);
      setUsername(profile.username);
      setRoles(profile.roles);
      setEquippedCosmetics(profile.equippedCosmetics);
      setIsAdmin(profile.isAdmin);
      // Avatar URL has to be refreshed here too — Settings.tsx calls
      // refreshProfile() after a successful avatar upload to pick up
      // the new image, and without this line the avatar stayed on
      // whatever value setActiveUser put in at login (often empty,
      // showing the initial-letter fallback in <Avatar>). The cache-bust
      // (see cacheBustedAvatar) forces a re-fetch from Supabase Storage's
      // CDN once per refreshProfile() call; avatars are small (<5 MB cap,
      // usually <100 KB after browser-side compression), so the extra
      // fetch per refresh is not a meaningful bandwidth concern.
      setAvatarUrl(cacheBustedAvatar(data.avatar_url, Date.now()));
      setFeaturedRole(profile.featuredRole);
    } catch {}
  }, [clearStaleClientAuth, setActiveUser]);

  useEffect(() => {
    if (userReady && userId) fetchProfileData(userId);
  }, [userReady, userId, fetchProfileData]);

  // #756: a 401 from ANY fetchJSON call (lib/api.ts onSessionExpired) means
  // the server may have stopped honouring this session — expired, signed out
  // elsewhere, account deleted. Re-check it at once with the same
  // GET /api/auth/me reconciliation as above instead of waiting for the next
  // profile refetch: a definitive 401/404 there clears the identity, the
  // user-scoped storage and the analytics identity, and bounces shell routes
  // to sign-in; a blip keeps the session. One check at a time, so a burst
  // of 401s costs one /me. Signed-out tabs (anonymous pages) have nothing to
  // check.
  const sessionCheck = React.useRef<Promise<void> | null>(null);
  useEffect(
    () =>
      onSessionExpired(() => {
        const uid = activeIdentity.current;
        if (!uid || sessionCheck.current) return;
        sessionCheck.current = fetchProfileData(uid).finally(() => {
          sessionCheck.current = null;
        });
      }),
    [fetchProfileData],
  );

  const refreshProfile = useCallback(async () => { await fetchProfileData(userId); }, [userId, fetchProfileData]);

  const markOnboarded = useCallback(() => setOnboardingCompleted(true), []);

  const signOut = useCallback(async () => {
    try {
      await fetch('/api/auth/session', { method: 'DELETE' });
    } finally {
      clearStaleClientAuth();
    }
  }, [clearStaleClientAuth]);

  const value = useMemo(
    () => ({
      // #757: no `isApproved` — nothing read it, and it sat false on a
      // localStorage boot. Approval is enforced server-side (the auth guard's
      // 403 not_approved, #756) and routed by the middleware (/pending).
      userId, userName, avatarUrl, userReady, isAuthenticated,
      username, roles, equippedCosmetics, featuredRole, isAdmin,
      setActiveUser, signOut, refreshProfile, setAvatarUrl,
      onboardingCompleted, markOnboarded,
    }),
    [userId, userName, avatarUrl, userReady, isAuthenticated,
     username, roles, equippedCosmetics, featuredRole, isAdmin, setActiveUser, refreshProfile, signOut,
     onboardingCompleted, markOnboarded]
  );

  return <UserContext.Provider value={value}>{children}</UserContext.Provider>;
}

export function useUser() { return useContext(UserContext); }
