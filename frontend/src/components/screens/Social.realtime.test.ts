import { describe, expect, it } from 'vitest';
import { mergeLatestMessages, planMessageRealtimeAction, planRoomRealtime } from './Social';

/**
 * #124: room_messages realtime payloads carry ciphertext `text`. The component
 * must treat a foreign message event as a "re-fetch via the decrypting REST
 * endpoint" signal rather than rendering payload.new.text. This tests the pure
 * decision that drives that behavior.
 */
const ME = 'user_me';
const THEM = 'user_other';

describe('planMessageRealtimeAction (#124)', () => {
  it('re-fetches on a foreign INSERT (never renders ciphertext payload)', () => {
    expect(planMessageRealtimeAction('INSERT', { id: 'm1', user_id: THEM }, ME))
      .toEqual({ type: 'refetch' });
  });

  it('ignores own INSERT echo (optimistic UI already has it)', () => {
    expect(planMessageRealtimeAction('INSERT', { id: 'm1', user_id: ME }, ME))
      .toEqual({ type: 'ignore' });
  });

  it('re-fetches on a foreign UPDATE (edit/delete carries ciphertext)', () => {
    expect(planMessageRealtimeAction('UPDATE', { id: 'm1', user_id: THEM }, ME))
      .toEqual({ type: 'refetch' });
  });

  it('applies only server flags on own UPDATE, keeping optimistic plaintext', () => {
    expect(
      planMessageRealtimeAction(
        'UPDATE',
        { id: 'm1', user_id: ME, is_deleted: true, edited_at: '2026-06-13T00:00:00Z' },
        ME,
      ),
    ).toEqual({ type: 'applyOwnFlags', id: 'm1', is_deleted: true, edited_at: '2026-06-13T00:00:00Z' });
  });

  it('ignores malformed events (no row / no id)', () => {
    expect(planMessageRealtimeAction('INSERT', null, ME)).toEqual({ type: 'ignore' });
    expect(planMessageRealtimeAction('UPDATE', { user_id: THEM }, ME)).toEqual({ type: 'ignore' });
  });
});

/**
 * #764: a foreign realtime insert used to call load(), which REPLACED the
 * list with the latest page and dropped every earlier page the user had
 * loaded. The refetch now merges.
 */
describe('mergeLatestMessages (#764)', () => {
  const msg = (id: string, minute: number, text = id) => ({
    id, text, created_at: `2026-06-13T00:${String(minute).padStart(2, '0')}:00Z`,
  });

  it('keeps earlier loaded pages and appends the new message', () => {
    const prev = [msg('old1', 1), msg('old2', 2), msg('a', 10), msg('b', 11)];
    const latest = [msg('a', 10), msg('b', 11), msg('c', 12)];
    expect(mergeLatestMessages(prev, latest).map(m => m.id))
      .toEqual(['old1', 'old2', 'a', 'b', 'c']);
  });

  it('takes the server row inside the latest window (foreign edit/delete)', () => {
    const prev = [msg('old1', 1), msg('a', 10, 'before')];
    const latest = [msg('a', 10, 'after')];
    const merged = mergeLatestMessages(prev, latest);
    expect(merged.map(m => [m.id, m.text])).toEqual([['old1', 'old1'], ['a', 'after']]);
  });

  it('keeps unsent optimistic rows at the end', () => {
    const prev = [msg('a', 10), msg('tmp_1', 30)];
    const latest = [msg('a', 10), msg('c', 12)];
    expect(mergeLatestMessages(prev, latest).map(m => m.id)).toEqual(['a', 'c', 'tmp_1']);
  });

  it('an empty refetch leaves the list alone', () => {
    const prev = [msg('a', 10)];
    expect(mergeLatestMessages(prev, [])).toBe(prev);
  });
});

/**
 * RLS step 2e (#115): the study-room channels join only on an applied minted
 * token. There is no anon path: room_messages has RLS on and no anon SELECT.
 * Without a token (first fetch, after expiry, or none this session after a
 * 503) the room waits on REST.
 */
describe('planRoomRealtime (RLS step 2e)', () => {
  it('joins only on an applied token', () => {
    expect(planRoomRealtime('token')).toBe('token');
  });

  it('waits for the minted token (first fetch, or after expiry)', () => {
    expect(planRoomRealtime('off')).toBe('wait');
    expect(planRoomRealtime('pending')).toBe('wait');
  });

  it('token permanently unavailable (404/503): REST only, never the anon key', () => {
    expect(planRoomRealtime('unavailable')).toBe('wait');
  });
});
