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
