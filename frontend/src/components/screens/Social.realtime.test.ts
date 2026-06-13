import { describe, expect, it } from 'vitest';
import { planMessageRealtimeAction } from './Social';

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
