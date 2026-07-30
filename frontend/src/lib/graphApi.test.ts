import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { addGraphNode } from './api';

/** Wire contract for the manual add-concept endpoint (#330). */

const realFetch = globalThis.fetch;

beforeEach(() => {
  globalThis.fetch = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ node: { id: 'n1' }, already_existed: false }), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    }),
  ) as unknown as typeof fetch;
});

afterEach(() => {
  globalThis.fetch = realFetch;
  vi.restoreAllMocks();
});

describe('addGraphNode', () => {
  it('POSTs the body to /api/graph/{userId}/nodes', async () => {
    const res = await addGraphNode('u1', {
      concept_name: 'Recursion', course_id: 'c1', anchor_node_id: 'n-root',
    });
    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/graph/u1/nodes');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({
      concept_name: 'Recursion', course_id: 'c1', anchor_node_id: 'n-root',
    });
    expect(res.already_existed).toBe(false);
  });
});
