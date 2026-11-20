/**
 * #866 K38: an `error` event a tutor stream ends with keeps its data on the
 * thrown ChatStreamError (`body`, as an ApiError keeps its parsed body), so a
 * crisis card the backend put there reaches `crisisSupportInError` — a
 * streamed start beside a note's card is never refused without the card
 * (docs/safety/crisis-support.md).
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

import fixture from '@/test-utils/crisisSupport.json';
import { crisisSupportInError } from './crisisSupport';

const sseBody = (blocks: string[]) => {
  const enc = new TextEncoder();
  return new ReadableStream({
    start(c) {
      for (const b of blocks) c.enqueue(enc.encode(b));
      c.close();
    },
  });
};
const ev = (name: string, data: unknown) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`;

afterEach(() => vi.restoreAllMocks());

async function failedStart(errorData: Record<string, unknown>): Promise<unknown> {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(
      sseBody([
        ev('token', { type: 'token', step: 'reply', message: '', data: { delta: "Let's" } }),
        ev('error', { type: 'error', step: 'reply', message: 'The tutor is unavailable.', data: errorData }),
      ]),
      { status: 200 },
    ) as never,
  );
  const { startSessionStream } = await import('./api');
  try {
    await startSessionStream('u1', 'Week 3', 'socratic', true, 'c1', undefined, { onToken: () => {} }, undefined, 'n1');
  } catch (err) {
    return err;
  }
  throw new Error('the stream resolved');
}

describe('a stream that ends in an error event', () => {
  it('keeps the event data on the ChatStreamError, the card with it', async () => {
    const err = await failedStart({ request_id: 'r1', retryable: false, crisis_support: fixture });
    const { ChatStreamError } = await import('./api');
    expect(err).toBeInstanceOf(ChatStreamError);
    const thrown = err as InstanceType<typeof ChatStreamError>;
    expect(thrown.retryable).toBe(false);
    expect(thrown.requestId).toBe('r1');
    expect(thrown.body).toEqual({ request_id: 'r1', retryable: false, crisis_support: fixture });
    expect(crisisSupportInError(err)).toEqual(fixture);
  });

  it('with no card in the event, there is none on the error', async () => {
    const err = await failedStart({ request_id: 'r1', retryable: false });
    expect(crisisSupportInError(err)).toBeNull();
  });
});
