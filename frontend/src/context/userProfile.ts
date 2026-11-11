import type { UserRole, EquippedCosmetics, Role } from '@/lib/types';

/** The profile part of a GET /api/auth/me answer (every field may be absent). */
export interface MeProfile {
  username?: string | null;
  roles?: UserRole[] | null;
  equipped_cosmetics?: EquippedCosmetics | null;
  is_admin?: boolean | null;
}

export interface ProfileFields {
  username: string | null;
  roles: UserRole[];
  equippedCosmetics: EquippedCosmetics;
  isAdmin: boolean;
  featuredRole: Role | null;
}

/**
 * #191: a definitive 401 (no live session) or 404 (user row gone — the
 * stale-session family) from /me means the identity this client holds is
 * dead. Anything else (5xx, 403, …) is not proof of that.
 */
export function isDeadSessionStatus(status: number): boolean {
  return status === 401 || status === 404;
}

/** The context's profile fields for a /me answer, with the absent ones defaulted. */
export function profileFields(data: MeProfile): ProfileFields {
  return {
    username: data.username ?? null,
    roles: data.roles ?? [],
    equippedCosmetics: data.equipped_cosmetics ?? {},
    isAdmin: data.is_admin ?? false,
    featuredRole: data.equipped_cosmetics?.featured_role ?? null,
  };
}

/**
 * The avatar URL to show, cache-busted with `v=<now>`: the storage URL is
 * deterministic (every upload writes `avatars/{user_id}/avatar.{ext}`), so a
 * re-upload would otherwise be served from the browser cache. '' when there
 * is no avatar. Throws, like the inline code it replaces, on a non-string.
 */
export function cacheBustedAvatar(avatarUrl: string | null | undefined, now: number): string {
  const rawAvatar = (avatarUrl ?? '').trim();
  if (!rawAvatar) return '';
  const sep = rawAvatar.includes('?') ? '&' : '?';
  return `${rawAvatar}${sep}v=${now}`;
}
