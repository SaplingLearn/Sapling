import { afterEach, describe, expect, it, vi } from 'vitest';
import { linkGradescopeCourse, listGradescopeLinks, syncGradescopeCourse, unlinkGradescopeCourse } from './api';

afterEach(() => vi.unstubAllGlobals());

describe('Gradescope semester scoping', () => {
  it('keeps list, link, sync and unlink in the selected semester', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => new Response('{}', {
      headers: { 'Content-Type': 'application/json' },
    }));
    vi.stubGlobal('fetch', fetchMock);

    await listGradescopeLinks('u1', 'Fall 2025');
    await linkGradescopeCourse('u1', 'course/1', '123', 'Fall 2025');
    await syncGradescopeCourse('u1', 'course/1', 'Fall 2025');
    await unlinkGradescopeCourse('u1', 'course/1', 'Fall 2025');

    expect(fetchMock.mock.calls[0][0]).toBe('/api/gradescope/links?user_id=u1&semester=Fall%202025');
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({
      user_id: 'u1', sapling_course_id: 'course/1', gradescope_course_id: '123', semester: 'Fall 2025',
    });
    expect(fetchMock.mock.calls[2][0]).toBe('/api/gradescope/sync/course%2F1?user_id=u1&semester=Fall%202025');
    expect(fetchMock.mock.calls[3][0]).toBe('/api/gradescope/link/course%2F1?user_id=u1&semester=Fall%202025');
    for (const [, options] of fetchMock.mock.calls) expect(options.credentials).toBe('include');
  });
});

describe('queued Gradescope sync (#116)', () => {
  const json = (status: number, body: unknown) => new Response(JSON.stringify(body), {
    status, headers: { 'Content-Type': 'application/json' },
  });
  const pending = { pending: true, sync_id: 's1', stage: 'running', detail: 'Still running.' };
  const counts = { inserted: 2, updated: 1, skipped: 0, failed: 0 };

  it('makes one POST and nothing else when the sync answers in the request', async () => {
    const fetchMock = vi.fn().mockResolvedValue(json(200, counts));
    vi.stubGlobal('fetch', fetchMock);
    const onPending = vi.fn();
    await expect(syncGradescopeCourse('u1', 'c1', undefined, { onPending, pollMs: 0 })).resolves.toEqual(counts);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(onPending).not.toHaveBeenCalled();
  });

  it('polls the status route after a 202 until the sync ends', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json(202, pending))
      .mockResolvedValueOnce(json(202, pending))
      .mockRejectedValueOnce(new TypeError('network blip'))
      .mockResolvedValueOnce(json(200, counts));
    vi.stubGlobal('fetch', fetchMock);
    const onPending = vi.fn();
    await expect(syncGradescopeCourse('u1', 'course/1', 'Fall 2025', { onPending, pollMs: 0 })).resolves.toEqual(counts);
    expect(onPending).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls[1][0]).toBe('/api/gradescope/sync/course%2F1/status?user_id=u1&semester=Fall%202025');
    expect(fetchMock.mock.calls[1][1]?.method).toBeUndefined();  // a GET
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it('rejects with the outcome the POST would have given', async () => {
    const reauth = { detail: 'Gradescope rejected the saved credentials. Reconnect Gradescope.',
                     error: { code: 'gradescope_reauth_required', message: 'x' } };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json(504, { detail: 'taking longer' }))
      .mockResolvedValueOnce(json(409, reauth));
    vi.stubGlobal('fetch', fetchMock);
    await expect(syncGradescopeCourse('u1', 'c1', undefined, { pollMs: 0 }))
      .rejects.toMatchObject({ status: 409, code: 'gradescope_reauth_required' });
  });

  it('keeps the 504 when there is no queued sync to wait for', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json(504, { detail: 'Gateway timeout' }))
      .mockResolvedValueOnce(json(404, { detail: 'No Gradescope sync found for this course' }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(syncGradescopeCourse('u1', 'c1', undefined, { pollMs: 0 }))
      .rejects.toMatchObject({ status: 504 });
  });

  it('does not poll after any other error', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(json(502, { detail: 'Couldn’t reach Gradescope.' }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(syncGradescopeCourse('u1', 'c1', undefined, { pollMs: 0 }))
      .rejects.toMatchObject({ status: 502 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
