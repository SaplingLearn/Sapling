// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest';
import {
  AGE_GATE_MS, YEAR_SPAN, ageOn, dayOptions, daysInMonth, isMinor, isUnder13, keepDay,
  rememberUnder13, under13Remembered, yearOptions,
} from './age';
import { USER_SCOPED_LOCAL_KEYS, USER_SCOPED_LOCAL_PREFIXES, clearUserScopedStorage } from '@/lib/userScopedStorage';

describe('ageOn', () => {
  it('counts a birthday later this year as not yet reached', () => {
    const today = new Date(2026, 10, 7);
    expect(ageOn(today, '11', '8', '2013')).toBe(12);
    expect(ageOn(today, '11', '7', '2013')).toBe(13);
    expect(ageOn(today, '', '7', '2013')).toBeNull();
  });

  it('sorts ages into under 13, 13-17 and adults', () => {
    expect([isUnder13(12), isUnder13(13), isUnder13(null)]).toEqual([true, false, false]);
    expect([isMinor(12), isMinor(13), isMinor(17), isMinor(18), isMinor(null)]).toEqual([false, true, true, false, false]);
  });
});

describe('the day and year lists', () => {
  it('has only the days the month and year have', () => {
    expect(daysInMonth('', '')).toBe(31);
    expect(daysInMonth('2', '')).toBe(29);
    expect(daysInMonth('2', '2001')).toBe(28);
    expect(daysInMonth('2', '2000')).toBe(29);
    expect(daysInMonth('4', '2001')).toBe(30);
    expect(dayOptions('4', '2001')).toHaveLength(30);
    expect(dayOptions('4', '2001').at(-1)).toEqual(['30', '30']);
  });

  it('drops a day the new month or year no longer has', () => {
    expect(keepDay('31', '4', '2001')).toBe('');
    expect(keepDay('29', '2', '2001')).toBe('');
    expect(keepDay('29', '2', '2004')).toBe('29');
    expect(keepDay('', '2', '2001')).toBe('');
  });

  it('goes back 100 years', () => {
    const years = yearOptions(new Date(2026, 0, 1));
    expect(YEAR_SPAN).toBe(100);
    expect(years[0]).toEqual(['2026', '2026']);
    expect(years.at(-1)).toEqual(['1926', '1926']);
    expect(years).toHaveLength(101);
  });
});

describe('the under-13 memory', () => {
  afterEach(() => localStorage.clear());
  const NOW = 1_800_000_000_000;

  it('holds for a day in this browser, then lapses', () => {
    expect(under13Remembered(NOW)).toBe(false);
    rememberUnder13(NOW);
    expect(under13Remembered(NOW + AGE_GATE_MS - 1)).toBe(true);
    expect(under13Remembered(NOW + AGE_GATE_MS)).toBe(false);
    expect(under13Remembered(NOW)).toBe(false);
  });

  it('survives a sign-out: it is about the browser, not the account', () => {
    rememberUnder13(NOW);
    clearUserScopedStorage();
    expect(under13Remembered(NOW + 1)).toBe(true);
    const key = 'sapling_age_gate_until';
    expect(USER_SCOPED_LOCAL_KEYS as readonly string[]).not.toContain(key);
    expect(USER_SCOPED_LOCAL_PREFIXES.some((p) => key.startsWith(p))).toBe(false);
  });

  it('ignores a stored time further out than a day', () => {
    localStorage.setItem('sapling_age_gate_until', String(NOW + 10 * AGE_GATE_MS));
    expect(under13Remembered(NOW)).toBe(false);
  });
});
