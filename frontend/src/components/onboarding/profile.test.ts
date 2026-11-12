// @vitest-environment jsdom
/**
 * Finishing onboarding: the name the save sends, the save's timeout, what each
 * failure means, and where a successful save goes next.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

const submitOnboardingProfile = vi.fn();
vi.mock('@/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api')>()),
  submitOnboardingProfile: (...a: unknown[]) => submitOnboardingProfile(...a),
}));

import { ApiError } from '@/lib/api';
import { EMPTY_DRAFT } from './draft';
import {
  SAVE_TIMEOUT_MS, SaveTimeoutError, classifySaveError, handoffFor, saveProfile, splitName,
} from './profile';

describe('splitName', () => {
  it('takes the last name from the account', () => {
    expect(splitName('Ada', 'Ada Lovelace')).toEqual({ first_name: 'Ada', last_name: 'Lovelace' });
    expect(splitName('  Countess  Ada ', 'Ada Lovelace')).toEqual({ first_name: 'Countess Ada', last_name: 'Lovelace' });
  });

  it('does not repeat a last name the student typed', () => {
    expect(splitName('Ada Lovelace', 'Ada Lovelace')).toEqual({ first_name: 'Ada', last_name: 'Lovelace' });
    expect(splitName('ada lovelace', 'Ada Lovelace')).toEqual({ first_name: 'ada', last_name: 'Lovelace' });
    expect(splitName('Mary Ann de la Cruz', 'Mary de la Cruz')).toEqual({ first_name: 'Mary Ann', last_name: 'de la Cruz' });
  });

  it('keeps a name that only ends like the last name', () => {
    expect(splitName('Adalovelace', 'Ada Lovelace')).toEqual({ first_name: 'Adalovelace', last_name: 'Lovelace' });
  });

  it('a field holding just the last name is the whole name', () => {
    expect(splitName('Lovelace', 'Ada Lovelace')).toEqual({ first_name: 'Lovelace', last_name: '' });
  });

  it('works with a one-word account name, and caps both at 80 characters', () => {
    expect(splitName('Ada', 'Ada')).toEqual({ first_name: 'Ada', last_name: '' });
    const { first_name, last_name } = splitName('y'.repeat(100), `Ada ${'x'.repeat(100)}`);
    expect(first_name.length).toBe(80);
    expect(last_name.length).toBe(80);
  });
});

describe('saveProfile', () => {
  afterEach(() => {
    vi.useRealTimers();
    submitOnboardingProfile.mockReset();
  });

  const draft = { ...EMPTY_DRAFT, name: 'Ada', year: 'junior', courses: [{ id: 'c1', course_code: 'CS 111', course_name: 'CS' }] };

  it('sends the courses, or none when the student will add them later', async () => {
    submitOnboardingProfile.mockResolvedValue({ ok: true });
    await saveProfile({ userId: 'u1', accountName: 'Ada Lovelace', draft, under18: false });
    expect(submitOnboardingProfile.mock.calls[0][0]).toMatchObject({ course_ids: ['c1'], under_18: false });
    await saveProfile({ userId: 'u1', accountName: 'Ada Lovelace', draft: { ...draft, coursesLater: true }, under18: true });
    expect(submitOnboardingProfile.mock.calls[1][0]).toMatchObject({ course_ids: [], under_18: true });
  });

  it(`gives up after ${SAVE_TIMEOUT_MS / 1000} s, and aborts the request`, async () => {
    vi.useFakeTimers();
    let signal: AbortSignal | undefined;
    submitOnboardingProfile.mockImplementation((_p: unknown, init: { signal: AbortSignal }) => {
      signal = init.signal;
      return new Promise(() => {});
    });
    const saving = saveProfile({ userId: 'u1', accountName: 'Ada Lovelace', draft, under18: false });
    const outcome = saving.catch((e: unknown) => e);
    vi.advanceTimersByTime(SAVE_TIMEOUT_MS - 1);
    expect(signal?.aborted).toBe(false);
    vi.advanceTimersByTime(1);
    const err = await outcome;
    expect(err).toBeInstanceOf(SaveTimeoutError);
    expect(signal?.aborted).toBe(true);
    expect(classifySaveError(err)).toEqual({
      kind: 'error', message: 'Saving took too long. Check your connection and try again.',
    });
  });
});

describe('classifySaveError', () => {
  const coded = (status: number, code: string) =>
    new ApiError(JSON.stringify({ detail: { code, message: 'm' } }), status, { body: { detail: { code, message: 'm' } } });

  it('names the failures the flow handles', () => {
    expect(classifySaveError(new ApiError('{"detail":"Onboarding is already complete."}', 409))).toEqual({ kind: 'already' });
    expect(classifySaveError(coded(403, 'not_approved'))).toEqual({ kind: 'not_approved' });
    expect(classifySaveError(coded(422, 'no_known_courses'))).toEqual({ kind: 'courses' });
    expect(classifySaveError(coded(422, 'legal_outdated'))).toEqual({ kind: 'legal' });
  });

  it('turns anything else into words, never raw JSON', () => {
    const validation = new ApiError('{"detail":[{"msg":"String should have at most 80 characters"}]}', 422, {
      body: { detail: [{ msg: 'String should have at most 80 characters' }] },
    });
    expect(classifySaveError(validation)).toEqual({ kind: 'error', message: 'String should have at most 80 characters' });
    expect(classifySaveError(new ApiError('{"x":{}}', 503, { body: { x: {} } }))).toEqual({
      kind: 'error', message: "That's temporarily unavailable. Try again in a moment.",
    });
    expect(classifySaveError(new TypeError('Failed to fetch'))).toEqual({
      kind: 'error', message: "We couldn't save your profile. Please try again.",
    });
    // A 403 for another reason is not "not approved".
    expect(classifySaveError(coded(403, 'something_else')).kind).toBe('error');
  });
});

describe('handoffFor', () => {
  it('goes to the dashboard, the gradebook, or Google Calendar consent (a full page load)', () => {
    expect(handoffFor('u1', {})).toEqual({ route: '/dashboard' });
    expect(handoffFor('u1', { gradescope: true })).toEqual({ route: '/gradebook' });
    expect(handoffFor('u1', { gcal: true })).toEqual({ page: '/api/calendar/auth-url?user_id=u1' });
    expect(handoffFor('u 1', { gcal: true, gradescope: true })).toEqual({
      page: '/api/calendar/auth-url?user_id=u%201&next=%2Fgradebook',
    });
    expect(handoffFor('u1', { gcal: false, gradescope: false })).toEqual({ route: '/dashboard' });
  });
});
