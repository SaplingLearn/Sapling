// @vitest-environment jsdom
/**
 * The Terms and Privacy answers are never stored: a resumed draft agrees to
 * them again, so what Finish sends is always the text this page showed.
 */
import { afterEach, describe, expect, it } from 'vitest';
import { EMPTY_DRAFT, forStorage, loadDraft, type Draft } from './draft';
import { LAST, screenIndex } from './flow';
import { readOnboardingDraft, writeOnboardingDraft } from '@/lib/onboardingDraft';

const AGREED: Draft = {
  ...EMPTY_DRAFT, name: 'Ada', lastName: 'Lovelace', school: 'bu', year: 'junior', coursesLater: true,
  screen: LAST, done: [0, 1, 2, 3, 4],
  termsEnd: true, termsOk: true, privEnd: true, privOk: true,
};

function resumed(saved: object): Draft | null {
  writeOnboardingDraft('user_a', saved);
  return loadDraft('user_a');
}

describe('the Terms and Privacy answers', () => {
  afterEach(() => localStorage.clear());

  it('are left out of what is stored', () => {
    writeOnboardingDraft('user_a', forStorage(AGREED));
    expect(readOnboardingDraft('user_a')).toMatchObject({
      termsEnd: false, termsOk: false, privEnd: false, privOk: false, name: 'Ada', lastName: 'Lovelace',
    });
  });

  it('are agreed to again: a draft saved past them resumes at the Terms', () => {
    expect(resumed(AGREED)).toEqual({
      ...AGREED, screen: screenIndex('terms'), termsEnd: false, termsOk: false, privEnd: false, privOk: false,
    });
  });

  it('are dropped, with their versions, from a draft saved before they stopped being stored', () => {
    const d = resumed({ ...AGREED, termsVersion: '2026-10-22', privacyVersion: '2026-11-03' });
    expect(d).toMatchObject({ screen: screenIndex('terms'), termsOk: false, privOk: false });
    expect(d).not.toHaveProperty('termsVersion');
    expect(d).not.toHaveProperty('privacyVersion');
  });

  it('leave a draft short of the legal screens where it was', () => {
    expect(resumed({ ...EMPTY_DRAFT, screen: 3 })?.screen).toBe(3);
  });
});
