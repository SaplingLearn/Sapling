import { describe, expect, it } from 'vitest';
import { presetRange } from './useAdminAnalytics';

// Pure date math for the dashboard's range presets. The default clock is
// lib/testMode's now() (frozen under NEXT_PUBLIC_TEST_MODE) — these tests pin
// the math itself with an explicit nowMs.

const NOW = Date.UTC(2026, 6, 30, 12, 0, 0); // 2026-07-30T12:00:00Z

describe('presetRange', () => {
  it('builds a last-N-days window ending now, in ISO UTC', () => {
    expect(presetRange(30, NOW)).toEqual({
      from: '2026-06-30T12:00:00.000Z',
      to: '2026-07-30T12:00:00.000Z',
    });
  });

  it('supports the 7-day preset', () => {
    expect(presetRange(7, NOW)).toEqual({
      from: '2026-07-23T12:00:00.000Z',
      to: '2026-07-30T12:00:00.000Z',
    });
  });
});
