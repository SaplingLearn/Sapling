'use client';

import React, { createContext, useContext, useState, useEffect, useMemo, useCallback } from 'react';
import type { UserRole, EquippedCosmetics, Role } from '@/lib/types';
import { IS_LOCAL_MODE } from '@/lib/api';
import { LOCAL_USER } from '@/lib/localData';

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
    if (IS_LOCAL_MODE) {
      setUserId(LOCAL_USER.id);
      setUserName(LOCAL_USER.name);
      setAvatarUrl(LOCAL_USER.avatar);
      setIsAuthenticated(true);
      setIsApproved(true);
      setIsAdmin(true);
      setUserReady(true);
      return;
    }
    const saved = localStorage.getItem('sapling_user');
    if (saved) {
      try {
        const { id, name, avatar } = JSON.parse(saved);
        setUserId(id);
        setUserName(name);
        if (avatar) setAvatarUrl(avatar);
        setIsAuthenticated(true);
      } catch {}
    }
    setUserReady(true);
  }, []);

  useEffect(() => {
    if (IS_LOCAL_MODE) return;
    fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/users`)
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
    if (!uid || IS_LOCAL_MODE) return;
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/auth/me?user_id=${encodeURIComponent(uid)}`);
      if (!res.ok) return;
      const data = await res.json();
      setUsername(data.username ?? null);
      setRoles(data.roles ?? []);
      setEquippedCosmetics(data.equipped_cosmetics ?? {});
      setIsAdmin(data.is_admin ?? false);
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
      if (typeof window !== 'undefined') {
        sessionStorage.removeItem('sapling_onboarding_pending');
      }
    }
  };

  const value = useMemo(
    () => ({
      userId, userName, avatarUrl, users, userReady, isAuthenticated, isApproved,
      username, roles, equippedCosmetics, featuredRole, isAdmin,
      setActiveUser, confirmApproved, signOut, refreshProfile,
    }),
    [userId, userName, avatarUrl, users, userReady, isAuthenticated, isApproved,
     username, roles, equippedCosmetics, featuredRole, isAdmin, refreshProfile]
  );

  return <UserContext.Provider value={value}>{children}</UserContext.Provider>;
}

export function useUser() { return useContext(UserContext); }
