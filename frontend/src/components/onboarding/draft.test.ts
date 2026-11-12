// @vitest-environment jsdom
/**
 * A draft's Terms and Privacy answers count only for the versions in force: a
 * resumed answer to an older text (or one saved without its version) starts
 * that screen over, and Finish needs both on today's versions.
 */
import { afterEach, describe, expect, it } from 'vitest';
import { EMPTY_DRAFT, legalAccepted, loadDraft, type Draft } from './draft';
import { LAST, screenIndex } from './flow';
import { PRIVACY_VERSION, TERMS_VERSION } from '@/lib/legal/versions';
import { writeOnboardingDraft } from '@/lib/onboardingDraft';

const ACCEPTED: Draft = {
  ...EMPTY_DRAFT, name: 'Ada', school: 'bu', year: 'junior', coursesLater: true, screen: LAST, done: [0, 1, 2, 3, 4],
  termsEnd: true, termsOk: true, termsVersion: TERMS_VERSION,
  privEnd: true, privOk: true, privacyVersion: PRIVACY_VERSION,
};

function resumed(saved: object): Draft | null {
  writeOnboardingDraft('user_a', saved);
  return loadDraft('user_a');
}

describe('the legal answers in a resumed draft', () => {
  afterEach(() => localStorage.clear());

  it('keeps answers to the versions in force as they were', () => {
    expect(resumed(ACCEPTED)).toEqual(ACCEPTED);
  });

  it('starts an older Terms over, and goes back to it', () => {
    const d = resumed({ ...ACCEPTED, termsVersion: '2026-01-01' });
    expect(d).toMatchObject({ screen: screenIndex('terms'), termsEnd: false, termsOk: false, termsVersion: '' });
    // The Privacy Policy accepted at today's version stays accepted.
    expect(d).toMatchObject({ privEnd: true, privOk: true, privacyVersion: PRIVACY_VERSION });
  });

  it('goes back only to the Privacy Policy when only it is older', () => {
    const d = resumed({ ...ACCEPTED, privacyVersion: '2026-01-01' });
    expect(d).toMatchObject({ screen: screenIndex('privacy'), termsOk: true, privEnd: false, privOk: false });
  });

  it('starts both over for answers saved without their versions', () => {
    const old: Partial<Draft> = { ...ACCEPTED };
    delete old.termsVersion;
    delete old.privacyVersion;
    expect(resumed(old)).toMatchObject({
      screen: screenIndex('terms'), termsEnd: false, termsOk: false, privEnd: false, privOk: false,
    });
  });

  it('leaves a draft short of the legal screens where it was', () => {
    expect(resumed({ ...EMPTY_DRAFT, screen: 3 })?.screen).toBe(3);
  });
});

describe('legalAccepted (what Finish needs)', () => {
  it('needs both boxes ticked on the versions in force', () => {
    expect(legalAccepted(ACCEPTED)).toBe(true);
    expect(legalAccepted({ ...ACCEPTED, termsVersion: '2026-01-01' })).toBe(false);
    expect(legalAccepted({ ...ACCEPTED, privacyVersion: '' })).toBe(false);
    expect(legalAccepted({ ...ACCEPTED, privOk: false })).toBe(false);
  });
});
