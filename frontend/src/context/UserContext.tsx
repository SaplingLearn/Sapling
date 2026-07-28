'use client';

import React, { createContext, useContext, useState, useEffect, useMemo, useCallback } from 'react';
import type { UserRole, EquippedCosmetics, Role } from '@/lib/types';
import { API_URL, getMe } from '@/lib/api';

interface UserOption {
  id: string;
  name: string;
}

interface UserContextValue {
  userId: string;
  userName: string;
  avatarUrl: string;
  users: UserOption[];
  userReady: boolean;
  isAuthenticated: boolean;
  isApproved: boolean;
  username: string | null;
  roles: UserRole[];
  equippedCosmetics: EquippedCosmetics;
  featuredRole: Role | null;
  isAdmin: boolean;
  setActiveUser: (id: string, name: string, avatar?: string) => void;
  confirmApproved: () => void;
  signOut: () => Promise<void>;
  refreshProfile: () => Promise<void>;
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
  users: [],
  userReady: false,
  isAuthenticated: false,
  isApproved: false,
  username: null,
  roles: [],
  equippedCosmetics: {},
  featuredRole: null,
  isAdmin: false,
  setActiveUser: () => {},
  confirmApproved: () => {},
  signOut: () => Promise.resolve(),
  refreshProfile: () => Promise.resolve(),
  setAvatarUrl: () => {},
});

export function UserProvider({ children }: { children: React.ReactNode }) {
  const [userId, setUserId] = useState('');
  const [userName, setUserName] = useState('');
  const [avatarUrl, setAvatarUrl] = useState('');
  const [users, setUsers] = useState<UserOption[]>([]);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isApproved, setIsApproved] = useState(false);
  const [userReady, setUserReady] = useState(false);

  const [username, setUsername] = useState<string | null>(null);
  const [roles, setRoles] = useState<UserRole[]>([]);
  const [equippedCosmetics, setEquippedCosmetics] = useState<EquippedCosmetics>({});
  const [featuredRole, setFeaturedRole] = useState<Role | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);

  useEffect(() => {
    const saved = localStorage.getItem('sapling_user');
    if (saved) {
      try {
        const { id, name, avatar } = JSON.parse(saved);
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
    (async () => {
      try {
        const me = await getMe();
        if (cancelled) return;
        // Write-through setActiveUser: hydrates state AND persists
        // localStorage, so the next bootstrap takes the fast synchronous
        // path above instead of hitting the network again.
        setActiveUser(me.user_id, me.name || '', me.avatar_url || '');
        if (me.is_approved) setIsApproved(true);
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
  }, []);

  useEffect(() => {
    fetch(`${API_URL}/api/users`, { credentials: 'include' })
      .then(r => r.json())
      .then((data: { users: UserOption[] }) => {
        const list = data.users ?? [];
        setUsers(list);
        setUserId(prev => {
          const match = list.find(u => u.id === prev);
          if (match) setUserName(match.name);
          return prev;
        });
      })
      .catch(() => {});
  }, []);

  const fetchProfileData = useCallback(async (uid: string) => {
    if (!uid) return;
    try {
      const res = await fetch(`${API_URL}/api/auth/me?user_id=${encodeURIComponent(uid)}`, { credentials: 'include' });
      if (!res.ok) return;
      const data = await res.json();
      setUsername(data.username ?? null);
      setRoles(data.roles ?? []);
      setEquippedCosmetics(data.equipped_cosmetics ?? {});
      setIsAdmin(data.is_admin ?? false);
      // Avatar URL has to be refreshed here too — Settings.tsx calls
      // refreshProfile() after a successful avatar upload to pick up
      // the new image, and without this line the avatar stayed on
      // whatever value setActiveUser put in at login (often empty,
      // showing the initial-letter fallback in <Avatar>).
      //
      // Cache-bust with `?v=<timestamp>` because the storage URL is
      // deterministic — every upload writes to
      // `avatars/{user_id}/avatar.{ext}`, so a re-upload produces an
      // identical URL and browsers serve the cached old image. The
      // timestamp changes on every refresh, which forces a re-fetch
      // from Supabase Storage's CDN once per refreshProfile() call.
      // Avatars are small (<5 MB cap, usually <100 KB after
      // browser-side compression), so the extra fetch per refresh is
      // not a meaningful bandwidth concern.
      const rawAvatar = (data.avatar_url ?? '').trim();
      if (rawAvatar) {
        const sep = rawAvatar.includes('?') ? '&' : '?';
        setAvatarUrl(`${rawAvatar}${sep}v=${Date.now()}`);
      } else {
        setAvatarUrl('');
      }
      const fr = data.equipped_cosmetics?.featured_role ?? null;
      setFeaturedRole(fr);
    } catch {}
  }, []);

  useEffect(() => {
    if (userReady && userId) fetchProfileData(userId);
  }, [userReady, userId, fetchProfileData]);

  const refreshProfile = useCallback(async () => { await fetchProfileData(userId); }, [userId, fetchProfileData]);

  const setActiveUser = (id: string, name: string, avatar?: string) => {
    setUserId(id);
    setUserName(name);
    if (avatar) setAvatarUrl(avatar);
    setIsAuthenticated(true);
    localStorage.setItem('sapling_user', JSON.stringify({ id, name, avatar: avatar || '' }));
  };

  const confirmApproved = () => setIsApproved(true);

  const signOut = async () => {
    try {
      await fetch('/api/auth/session', { method: 'DELETE' });
    } finally {
      setUserId('');
      setUserName('');
      setAvatarUrl('');
      setIsAuthenticated(false);
      setIsApproved(false);
      setUsername(null);
      setRoles([]);
      setEquippedCosmetics({});
      setFeaturedRole(null);
      setIsAdmin(false);
      localStorage.removeItem('sapling_user');
    }
  };

  const value = useMemo(
    () => ({
      userId, userName, avatarUrl, users, userReady, isAuthenticated, isApproved,
      username, roles, equippedCosmetics, featuredRole, isAdmin,
      setActiveUser, confirmApproved, signOut, refreshProfile, setAvatarUrl,
    }),
    [userId, userName, avatarUrl, users, userReady, isAuthenticated, isApproved,
     username, roles, equippedCosmetics, featuredRole, isAdmin, refreshProfile]
  );

  return <UserContext.Provider value={value}>{children}</UserContext.Provider>;
}

export function useUser() { return useContext(UserContext); }
