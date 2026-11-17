import { describe, it, expect } from 'vitest';
import { cacheBustedAvatar, isDeadSessionStatus, profileFields } from './userProfile';
import type { Role } from '@/lib/types';

const role: Role = {
  id: 'r1', name: 'Mentor', slug: 'mentor', color: '#000', icon: null,
  description: null, is_staff_assigned: false, is_earnable: true, display_priority: 1,
} as Role;

describe('isDeadSessionStatus', () => {
  it.each([401, 404])('%i is a dead session', status => {
    expect(isDeadSessionStatus(status)).toBe(true);
  });
  it.each([200, 400, 403, 409, 500, 502, 503])('%i is not', status => {
    expect(isDeadSessionStatus(status)).toBe(false);
  });
});

describe('profileFields', () => {
  it('maps every field', () => {
    const roles = [{ role, granted_at: 't' }];
    const cosmetics = { featured_role: role };
    expect(profileFields({ username: 'u', roles, equipped_cosmetics: cosmetics, is_admin: true })).toEqual({
      username: 'u', roles, equippedCosmetics: cosmetics, isAdmin: true, featuredRole: role,
    });
  });

  it('defaults absent fields', () => {
    expect(profileFields({})).toEqual({
      username: null, roles: [], equippedCosmetics: {}, isAdmin: false, featuredRole: null,
    });
  });

  it('defaults null fields', () => {
    expect(profileFields({ username: null, roles: null, equipped_cosmetics: null, is_admin: null })).toEqual({
      username: null, roles: [], equippedCosmetics: {}, isAdmin: false, featuredRole: null,
    });
  });

  it('keeps falsy non-null values (?? not ||)', () => {
    expect(profileFields({ username: '', roles: [], is_admin: false })).toMatchObject({
      username: '', roles: [], isAdmin: false,
    });
  });

  it('cosmetics without a featured role → featuredRole null', () => {
    expect(profileFields({ equipped_cosmetics: {} }).featuredRole).toBeNull();
  });
});

describe('cacheBustedAvatar', () => {
  it('appends ?v= to a bare URL, trimmed', () => {
    expect(cacheBustedAvatar('  https://cdn/a.png ', 7)).toBe('https://cdn/a.png?v=7');
  });
  it('appends &v= when the URL has a query', () => {
    expect(cacheBustedAvatar('https://cdn/a.png?t=1', 7)).toBe('https://cdn/a.png?t=1&v=7');
  });
  it.each([undefined, null, '', '   '])('%j → empty', raw => {
    expect(cacheBustedAvatar(raw, 7)).toBe('');
  });
  it('throws on a non-string (callers rely on the throw ordering)', () => {
    expect(() => cacheBustedAvatar(42 as unknown as string, 7)).toThrow(TypeError);
  });
});
