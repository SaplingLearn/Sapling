// @vitest-environment jsdom
/**
 * The onboarding draft's storage: one key per account (#757), a seven-day
 * expiry, and no guest drafts (sign in first, 2026-11-12).
 */
import { afterEach, describe, expect, it } from 'vitest';
import {
  DRAFT_TTL_MS, GUEST_DRAFT_KEY, clearOnboardingDraft, onboardingDraftKey,
  purgeGuestOnboardingDraft, readOnboardingDraft, writeOnboardingDraft,
} from './onboardingDraft';
import { USER_SCOPED_LOCAL_PREFIXES } from './userScopedStorage';

const NOW = 1_800_000_000_000;

describe('onboarding draft storage', () => {
  afterEach(() => localStorage.clear());

  it('keys a draft by account, under the prefix sign-out clears', () => {
    expect(onboardingDraftKey('user_a')).toBe('sapling_onboarding_draft:user_a');
    expect(USER_SCOPED_LOCAL_PREFIXES.some((p) => onboardingDraftKey('user_a').startsWith(p))).toBe(true);
  });

  it('writes the draft stamped with the time and reads it back without the stamp', () => {
    writeOnboardingDraft('user_a', { name: 'Ada', screen: 2 }, NOW);
    expect(JSON.parse(localStorage.getItem(onboardingDraftKey('user_a'))!).savedAt).toBe(NOW);
    expect(readOnboardingDraft('user_a', NOW + 1000)).toEqual({ name: 'Ada', screen: 2 });
  });

  it('expires a draft after seven days, and removes it', () => {
    writeOnboardingDraft('user_a', { name: 'Ada' }, NOW);
    expect(readOnboardingDraft('user_a', NOW + DRAFT_TTL_MS - 1)).toEqual({ name: 'Ada' });
    expect(readOnboardingDraft('user_a', NOW + DRAFT_TTL_MS)).toBeNull();
    expect(localStorage.getItem(onboardingDraftKey('user_a'))).toBeNull();
  });

  it('treats an unstamped, garbled or far-future draft as gone', () => {
    localStorage.setItem(onboardingDraftKey('user_a'), JSON.stringify({ name: 'Ada' }));
    expect(readOnboardingDraft('user_a', NOW)).toBeNull();
    localStorage.setItem(onboardingDraftKey('user_a'), '{nope');
    expect(readOnboardingDraft('user_a', NOW)).toBeNull();
    expect(localStorage.getItem(onboardingDraftKey('user_a'))).toBeNull();
    writeOnboardingDraft('user_a', { name: 'Ada' }, NOW + 10 * 60 * 1000);
    expect(readOnboardingDraft('user_a', NOW)).toBeNull();
  });

  it('drops the pre-#757 shared key on read', () => {
    localStorage.setItem('sapling_onboarding_draft', JSON.stringify({ name: 'Legacy' }));
    readOnboardingDraft('user_a', NOW);
    expect(localStorage.getItem('sapling_onboarding_draft')).toBeNull();
  });

  it('clears one account and purges only the guest key', () => {
    writeOnboardingDraft('user_a', { name: 'Ada' }, NOW);
    localStorage.setItem(GUEST_DRAFT_KEY, JSON.stringify({ name: 'Guest' }));
    purgeGuestOnboardingDraft();
    expect(localStorage.getItem(GUEST_DRAFT_KEY)).toBeNull();
    expect(localStorage.getItem(onboardingDraftKey('user_a'))).not.toBeNull();
    clearOnboardingDraft('user_a');
    expect(localStorage.getItem(onboardingDraftKey('user_a'))).toBeNull();
  });

  it('reads nothing for no account', () => {
    expect(readOnboardingDraft('', NOW)).toBeNull();
  });
});
