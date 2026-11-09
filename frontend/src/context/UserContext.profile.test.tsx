// @vitest-environment jsdom
/**
 * Characterization of UserProvider's profile load (fetchProfileData): how a
 * GET /api/auth/me?user_id= answer maps onto the context, which fields keep
 * their old value when the answer leaves them out, the display-name
 * write-through, and the failure paths that must leave the tab untouched.
 */
import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, waitFor, act, fireEvent } from '@testing-library/react';

vi.mock('@/lib/api', () => ({
  API_URL: '',
  getMe: vi.fn().mockRejectedValue(new Error('not used in these tests')),
  onSessionExpired: () => () => {},
}));

import { UserProvider, useUser } from './UserContext';

function FullProbe() {
  const u = useUser();
  return (
    <div data-testid="full">
      {JSON.stringify({
        ready: u.userReady,
        auth: u.isAuthenticated,
        userId: u.userId,
        userName: u.userName,
        avatarUrl: u.avatarUrl,
        username: u.username,
        roles: u.roles,
        equippedCosmetics: u.equippedCosmetics,
        featuredRole: u.featuredRole,
        isAdmin: u.isAdmin,
      })}
    </div>
  );
}

function HydrateButton() {
  const { setActiveUser } = useUser();
  return <button onClick={() => setActiveUser('u-9', 'Nine', '', { persist: false })}>hydrate</button>;
}

const read = () => JSON.parse(screen.getByTestId('full').textContent ?? '{}');

function stubMe(body: () => Promise<unknown>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes('/api/auth/me')) return { ok: true, status: 200, json: body } as unknown as Response;
    return { ok: true, status: 200, json: async () => ({}) } as Response;
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

const seed = (user: Record<string, unknown> = { id: 'u-1', name: 'Saved Name', avatar: 'https://cdn/old.png' }) =>
  localStorage.setItem('sapling_user', JSON.stringify(user));

function mount() {
  return render(
    <UserProvider>
      <FullProbe />
    </UserProvider>,
  );
}

const settle = () => act(async () => new Promise(r => setTimeout(r, 20)));

const role = { id: 'r1', name: 'Mentor', slug: 'mentor', color: '#000', icon: null, description: null, is_staff_assigned: false, is_earnable: true, display_priority: 1 };

describe('fetchProfileData: success mapping', () => {
  beforeEach(() => {
    localStorage.clear();
    window.history.replaceState({}, '', '/');
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('requests /me for the encoded id with credentials', async () => {
    seed({ id: 'u 1/x?y', name: 'N', avatar: '' });
    const fetchMock = stubMe(async () => ({ user_id: 'u 1/x?y', roles: [] }));
    mount();
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(fetchMock).toHaveBeenCalledWith('/api/auth/me?user_id=u%201%2Fx%3Fy', { credentials: 'include' });
  });

  it('maps every profile field and cache-busts the avatar with ?v=', async () => {
    seed();
    stubMe(async () => ({
      user_id: 'u-1',
      name: 'Fresh Name',
      username: 'fresh',
      roles: [{ role, granted_at: 't' }],
      equipped_cosmetics: { featured_role: role, name_color: 'c' },
      is_admin: true,
      avatar_url: '  https://cdn/a.png  ',
    }));
    mount();
    await waitFor(() => expect(read().username).toBe('fresh'));
    const s = read();
    expect(s.userName).toBe('Fresh Name');
    expect(s.roles).toEqual([{ role, granted_at: 't' }]);
    expect(s.equippedCosmetics).toEqual({ featured_role: role, name_color: 'c' });
    expect(s.featuredRole).toEqual(role);
    expect(s.isAdmin).toBe(true);
    expect(s.avatarUrl).toMatch(/^https:\/\/cdn\/a\.png\?v=\d+$/);
    expect(s.auth).toBe(true);
    expect(s.userId).toBe('u-1');
    // The confirmed name is written through; the stored avatar is not touched.
    expect(JSON.parse(localStorage.getItem('sapling_user') ?? 'null')).toEqual({
      id: 'u-1', name: 'Fresh Name', avatar: 'https://cdn/old.png',
    });
  });

  it('appends &v= when the avatar URL already has a query', async () => {
    seed();
    stubMe(async () => ({ user_id: 'u-1', avatar_url: 'https://cdn/a.png?token=1' }));
    mount();
    await waitFor(() => expect(read().avatarUrl).toMatch(/^https:\/\/cdn\/a\.png\?token=1&v=\d+$/));
  });

  it('missing fields: defaults for profile fields, name kept, avatar cleared', async () => {
    seed();
    stubMe(async () => ({}));
    mount();
    await waitFor(() => expect(read().avatarUrl).toBe(''));
    const s = read();
    expect(s).toMatchObject({
      auth: true,
      userId: 'u-1',
      userName: 'Saved Name',
      username: null,
      roles: [],
      equippedCosmetics: {},
      featuredRole: null,
      isAdmin: false,
    });
    expect(JSON.parse(localStorage.getItem('sapling_user') ?? 'null')).toEqual({
      id: 'u-1', name: 'Saved Name', avatar: 'https://cdn/old.png',
    });
  });

  it('null fields: same defaults; whitespace-only avatar clears it; empty name kept', async () => {
    seed();
    stubMe(async () => ({
      user_id: 'u-1',
      name: '',
      username: null,
      roles: null,
      equipped_cosmetics: null,
      is_admin: null,
      avatar_url: '   ',
    }));
    mount();
    await waitFor(() => expect(read().avatarUrl).toBe(''));
    expect(read()).toMatchObject({
      userName: 'Saved Name',
      username: null,
      roles: [],
      equippedCosmetics: {},
      featuredRole: null,
      isAdmin: false,
    });
  });

  it('cosmetics without a featured role → featuredRole null', async () => {
    seed();
    stubMe(async () => ({ user_id: 'u-1', username: 'x', equipped_cosmetics: { name_color: 'c' } }));
    mount();
    await waitFor(() => expect(read().username).toBe('x'));
    expect(read().featuredRole).toBeNull();
    expect(read().equippedCosmetics).toEqual({ name_color: 'c' });
  });

  it('is_admin false stays false (?? keeps falsy values)', async () => {
    seed();
    stubMe(async () => ({ user_id: 'u-1', username: '', is_admin: false, roles: [] }));
    mount();
    await waitFor(() => expect(read().avatarUrl).toBe(''));
    expect(read().username).toBe('');
    expect(read().isAdmin).toBe(false);
  });

  it('an answer with no user_id is applied to the current account', async () => {
    seed();
    stubMe(async () => ({ name: 'No Id', username: 'noid' }));
    mount();
    await waitFor(() => expect(read().username).toBe('noid'));
    expect(read()).toMatchObject({ auth: true, userId: 'u-1', userName: 'No Id' });
  });

  it('the same name is not rewritten to localStorage', async () => {
    seed();
    const setItem = vi.spyOn(Storage.prototype, 'setItem');
    stubMe(async () => ({ user_id: 'u-1', name: 'Saved Name', username: 'same' }));
    mount();
    await waitFor(() => expect(read().username).toBe('same'));
    expect(setItem).not.toHaveBeenCalled();
  });

  it('a failing localStorage write is swallowed and the rest still applies', async () => {
    seed();
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota');
    });
    stubMe(async () => ({ user_id: 'u-1', name: 'New', username: 'still', is_admin: true }));
    mount();
    await waitFor(() => expect(read().username).toBe('still'));
    expect(read()).toMatchObject({ userName: 'New', isAdmin: true });
  });

  it('a stored copy for another id is not rewritten', async () => {
    let finish!: (body: unknown) => void;
    const body = new Promise(resolve => { finish = resolve; });
    stubMe(() => body);
    render(
      <UserProvider>
        <FullProbe />
        <HydrateButton />
      </UserProvider>,
    );
    await waitFor(() => expect(read().ready).toBe(true));
    fireEvent.click(screen.getByText('hydrate'));
    await waitFor(() => expect(read().userId).toBe('u-9'));
    localStorage.setItem('sapling_user', JSON.stringify({ id: 'other', name: 'Other' }));
    await act(async () => {
      finish({ user_id: 'u-9', name: 'Fresh', username: 'nine' });
      await body;
    });
    expect(read()).toMatchObject({ userName: 'Fresh', username: 'nine' });
    expect(JSON.parse(localStorage.getItem('sapling_user') ?? 'null')).toEqual({ id: 'other', name: 'Other' });
  });
});

describe('fetchProfileData: failures leave the tab as it was', () => {
  beforeEach(() => {
    localStorage.clear();
    window.history.replaceState({}, '', '/');
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  const bootState = {
    auth: true,
    userId: 'u-1',
    userName: 'Saved Name',
    avatarUrl: 'https://cdn/old.png',
    username: null,
    roles: [],
    equippedCosmetics: {},
    featuredRole: null,
    isAdmin: false,
  };

  it('a body that fails to parse is swallowed', async () => {
    seed();
    const body = vi.fn(async () => {
      throw new SyntaxError('bad json');
    });
    stubMe(body);
    mount();
    await waitFor(() => expect(body).toHaveBeenCalled());
    await settle();
    expect(read()).toMatchObject(bootState);
    expect(JSON.parse(localStorage.getItem('sapling_user') ?? 'null')).toMatchObject({ id: 'u-1' });
  });

  it('a null body is swallowed', async () => {
    seed();
    const body = vi.fn(async () => null);
    stubMe(body);
    mount();
    await waitFor(() => expect(body).toHaveBeenCalled());
    await settle();
    expect(read()).toMatchObject(bootState);
  });

  it('a non-string avatar stops the update after isAdmin (avatar and featured role untouched)', async () => {
    seed();
    stubMe(async () => ({
      user_id: 'u-1',
      name: 'Partial',
      username: 'part',
      roles: [{ role, granted_at: 't' }],
      equipped_cosmetics: { featured_role: role },
      is_admin: true,
      avatar_url: 42,
    }));
    mount();
    await waitFor(() => expect(read().username).toBe('part'));
    await settle();
    expect(read()).toMatchObject({
      userName: 'Partial',
      username: 'part',
      roles: [{ role, granted_at: 't' }],
      equippedCosmetics: { featured_role: role },
      isAdmin: true,
      avatarUrl: 'https://cdn/old.png',
      featuredRole: null,
    });
    expect(JSON.parse(localStorage.getItem('sapling_user') ?? 'null')).toMatchObject({ name: 'Partial' });
  });

  it.each([400, 403, 500])('a %i keeps the identity and profile untouched', async status => {
    seed();
    const fetchMock = vi.fn(async () => ({ ok: false, status, json: async () => ({ username: 'nope' }) }));
    vi.stubGlobal('fetch', fetchMock);
    mount();
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await settle();
    expect(read()).toMatchObject(bootState);
    expect(localStorage.getItem('sapling_user')).not.toBeNull();
  });

  it('a 401 clears every profile field and the stored identity', async () => {
    seed();
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 401, json: async () => ({}) })));
    mount();
    await waitFor(() => expect(read().auth).toBe(false));
    expect(read()).toMatchObject({
      userId: '', userName: '', avatarUrl: '', username: null, roles: [],
      equippedCosmetics: {}, featuredRole: null, isAdmin: false,
    });
    expect(localStorage.getItem('sapling_user')).toBeNull();
  });

  it('a mismatched answer adopts the session user with its avatar', async () => {
    seed();
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('user_id=u-1')) {
        return { ok: true, status: 200, json: async () => ({ user_id: 'u-2', avatar_url: 'https://cdn/b.png' }) };
      }
      return { ok: true, status: 200, json: async () => ({ user_id: 'u-2', username: 'second' }) };
    });
    vi.stubGlobal('fetch', fetchMock);
    mount();
    await waitFor(() => expect(read().username).toBe('second'));
    expect(read()).toMatchObject({ auth: true, userId: 'u-2', userName: '' });
    expect(JSON.parse(localStorage.getItem('sapling_user') ?? 'null')).toEqual({
      id: 'u-2', name: '', avatar: 'https://cdn/b.png',
    });
  });
});
