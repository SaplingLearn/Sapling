import { describe, expect, it } from 'vitest';
import { checkFrontendDeployEnv } from './deployGuard';

const PROD = {
  NEXT_PUBLIC_API_URL: 'https://api.saplinglearn.com',
  BACKEND_URL: 'https://api.saplinglearn.com',
  COOKIE_DOMAIN: '.saplinglearn.com',
};
const STAGING = {
  NEXT_PUBLIC_API_URL: 'https://api.staging.saplinglearn.com',
  BACKEND_URL: 'https://api.staging.saplinglearn.com',
  COOKIE_DOMAIN: '.staging.saplinglearn.com',
};

describe('checkFrontendDeployEnv', () => {
  it('passes a clean prod config', () => {
    expect(checkFrontendDeployEnv(PROD)).toEqual([]);
  });

  it('passes a clean staging config', () => {
    expect(checkFrontendDeployEnv(STAGING)).toEqual([]);
  });

  it('passes prod values with a matching DEPLOY_ENV', () => {
    expect(checkFrontendDeployEnv({ ...PROD, DEPLOY_ENV: 'production' })).toEqual([]);
  });

  it('flags split-brain: prod API URL with a staging cookie domain', () => {
    const problems = checkFrontendDeployEnv({ ...PROD, COOKIE_DOMAIN: '.staging.saplinglearn.com' });
    expect(problems.some((p) => /mix environments/.test(p))).toBe(true);
  });

  it('catches the real bug: all-staging values on a prod deploy (DEPLOY_ENV=production)', () => {
    const problems = checkFrontendDeployEnv({ ...STAGING, DEPLOY_ENV: 'production' });
    expect(problems.some((p) => /DEPLOY_ENV=production/.test(p))).toBe(true);
  });

  it('rejects an unknown DEPLOY_ENV', () => {
    const problems = checkFrontendDeployEnv({ ...PROD, DEPLOY_ENV: 'prod' });
    expect(problems.some((p) => /DEPLOY_ENV must be one of/.test(p))).toBe(true);
  });

  it('is a no-op when the variables are unset (local/dev build)', () => {
    expect(checkFrontendDeployEnv({})).toEqual([]);
  });

  it('ignores non-canonical values (e.g. a preview URL) rather than failing', () => {
    expect(
      checkFrontendDeployEnv({ NEXT_PUBLIC_API_URL: 'https://preview.example.workers.dev' }),
    ).toEqual([]);
  });

  it('tolerates case/whitespace differences in values', () => {
    expect(
      checkFrontendDeployEnv({
        NEXT_PUBLIC_API_URL: '  https://API.saplinglearn.com  ',
        COOKIE_DOMAIN: '.saplinglearn.com',
        DEPLOY_ENV: 'production',
      }),
    ).toEqual([]);
  });
});
