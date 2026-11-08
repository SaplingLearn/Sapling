import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, fetchJSON, getPendingStatus, onSessionExpired } from './api';

/** #756: a 401 from any session-authenticated call reaches the listeners. */
describe('fetchJSON — global 401 (#756)', () => {
  const realFetch = globalThis.fetch;
  let unsubscribe: () => void = () => {};
  const listener = vi.fn();

  const answer = (status: number, body: unknown = { detail: 'x' }) => {
    globalThis.fetch = vi.fn(async () =>
      new Response(JSON.stringify(body), { status }),
    ) as unknown as typeof fetch;
  };

  beforeEach(() => {
    listener.mockReset();
    unsubscribe = onSessionExpired(listener);
  });

  afterEach(() => {
    unsubscribe();
    globalThis.fetch = realFetch;
  });

  it('notifies on a 401 and still rejects with the ApiError', async () => {
    answer(401, { detail: 'Not authenticated' });
    const err = await fetchJSON('/api/graph/u').catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(401);
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it.each([403, 404, 429, 500])('does not notify on a %s', async (status) => {
    answer(status);
    await fetchJSON('/api/graph/u').catch(() => {});
    expect(listener).not.toHaveBeenCalled();
  });

  it('does not notify on success', async () => {
    answer(200, { ok: true });
    await fetchJSON('/api/graph/u');
    expect(listener).not.toHaveBeenCalled();
  });

  it("ignores the pending-token endpoints' 401 (not a session)", async () => {
    answer(401);
    await getPendingStatus('tok').catch(() => {});
    expect(listener).not.toHaveBeenCalled();
  });

  it('stops notifying after unsubscribe', async () => {
    unsubscribe();
    answer(401);
    await fetchJSON('/api/graph/u').catch(() => {});
    expect(listener).not.toHaveBeenCalled();
  });

  it('a throwing listener does not break the request or the other listeners', async () => {
    const other = vi.fn();
    const offBad = onSessionExpired(() => {
      throw new Error('boom');
    });
    const offOther = onSessionExpired(other);
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
    answer(401);
    const err = await fetchJSON('/api/graph/u').catch((e: unknown) => e);
    expect((err as ApiError).status).toBe(401);
    expect(other).toHaveBeenCalledTimes(1);
    offBad();
    offOther();
    consoleError.mockRestore();
  });
});
