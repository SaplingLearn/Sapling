import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createRoom, joinPublicRoom, listPublicRooms } from './api';

/** Wire contracts for the #405 rooms semantics: create carries the new
 * optional fields; the public surface lists and joins without an invite. */

const realFetch = globalThis.fetch;

beforeEach(() => {
  globalThis.fetch = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ room_id: 'r1', invite_code: 'ABC', rooms: [], joined: true }), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    }),
  ) as unknown as typeof fetch;
});

afterEach(() => {
  globalThis.fetch = realFetch;
  vi.restoreAllMocks();
});

const lastCall = () => {
  const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
  return fetchMock.mock.calls.at(-1) as [string, RequestInit | undefined];
};

describe('createRoom', () => {
  it('stays back-compatible without options', async () => {
    await createRoom('u1', 'Algebra crew');
    const [, init] = lastCall();
    expect(JSON.parse(init!.body as string)).toEqual({ user_id: 'u1', room_name: 'Algebra crew' });
  });

  it('forwards topic/course/is_public when given', async () => {
    await createRoom('u1', 'Algebra crew', { topic: 'Midterm prep', course: 'MATH210', is_public: true });
    const [, init] = lastCall();
    expect(JSON.parse(init!.body as string)).toEqual({
      user_id: 'u1', room_name: 'Algebra crew',
      topic: 'Midterm prep', course: 'MATH210', is_public: true,
    });
  });
});

describe('public rooms', () => {
  it('listPublicRooms hits the public listing with the user id', async () => {
    await listPublicRooms('u1');
    const [url] = lastCall();
    expect(url).toBe('/api/social/public-rooms?user_id=u1');
  });

  it('joinPublicRoom POSTs the invite-less join', async () => {
    await joinPublicRoom('u2', 'r-pub');
    const [url, init] = lastCall();
    expect(url).toBe('/api/social/public-rooms/r-pub/join');
    expect(JSON.parse(init!.body as string)).toEqual({ user_id: 'u2' });
  });
});
