import { describe, expect, it } from 'vitest';
import {
  checkFrontendDeployEnv,
  resolveFrontendEnv,
  expectedEnvForHost,
  detectHostConfigMismatch,
  FRONTEND_ENVS,
} from './deployGuard';

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

  // A trailing slash is a valid spelling of the same origin, but classify()
  // used to compare it literally, so `https://api.saplinglearn.com/` matched
  // nothing and the guard stopped seeing the variable AT ALL — a mixed or
  // wrong-environment config passed silently, which is the whole bug the guard
  // exists to catch. Each of these fails against the unnormalised comparison.
  it('sees a trailing-slash prod API URL well enough to flag a staging cookie domain', () => {
    const problems = checkFrontendDeployEnv({
      NEXT_PUBLIC_API_URL: 'https://api.saplinglearn.com/',
      COOKIE_DOMAIN: '.staging.saplinglearn.com',
    });
    expect(problems).toHaveLength(1);
    expect(problems[0]).toMatch(/mix environments/);
  });

  it('catches a trailing-slash staging API URL on a DEPLOY_ENV=production build', () => {
    // No COOKIE_DOMAIN on purpose: the slashed URLs are the ONLY signal, so an
    // unnormalised classify() finds nothing to complain about.
    const problems = checkFrontendDeployEnv({
      NEXT_PUBLIC_API_URL: 'https://api.staging.saplinglearn.com/',
      BACKEND_URL: 'https://api.staging.saplinglearn.com/',
      DEPLOY_ENV: 'production',
    });
    expect(problems).toHaveLength(1);
    expect(problems[0]).toMatch(/DEPLOY_ENV=production/);
  });

  it('catches a trailing-slash staging site URL on a DEPLOY_ENV=production build', () => {
    const problems = checkFrontendDeployEnv({
      NEXT_PUBLIC_SITE_URL: 'https://staging.saplinglearn.com/',
      DEPLOY_ENV: 'production',
    });
    expect(problems).toHaveLength(1);
    expect(problems[0]).toMatch(/NEXT_PUBLIC_SITE_URL→staging/);
  });

  it('flags a trailing-slash prod site URL mixed with staging API vars', () => {
    const problems = checkFrontendDeployEnv({
      NEXT_PUBLIC_SITE_URL: 'https://saplinglearn.com/',
      NEXT_PUBLIC_API_URL: 'https://api.staging.saplinglearn.com',
      COOKIE_DOMAIN: '.staging.saplinglearn.com',
    });
    expect(problems).toHaveLength(1);
    expect(problems[0]).toMatch(/mix environments/);
  });

  it('does not false-positive on a fully slashed, internally consistent config', () => {
    expect(
      checkFrontendDeployEnv({
        NEXT_PUBLIC_API_URL: 'https://api.saplinglearn.com/',
        BACKEND_URL: 'https://api.saplinglearn.com/',
        NEXT_PUBLIC_SITE_URL: 'https://saplinglearn.com/',
        COOKIE_DOMAIN: '.saplinglearn.com',
        DEPLOY_ENV: 'production',
      }),
    ).toEqual([]);
  });

  // cookieDomain is a `Domain` attribute, not a URL: a trailing slash in it is
  // genuinely malformed, so it must stay unrecognised. Normalising it too would
  // classify this as staging and flag a DEPLOY_ENV=production mismatch.
  it('does not normalise a trailing slash in COOKIE_DOMAIN', () => {
    expect(
      checkFrontendDeployEnv({
        NEXT_PUBLIC_API_URL: 'https://api.saplinglearn.com',
        COOKIE_DOMAIN: '.staging.saplinglearn.com/',
        DEPLOY_ENV: 'production',
      }),
    ).toEqual([]);
  });
});

describe('resolveFrontendEnv', () => {
  it('derives all values from DEPLOY_ENV=staging (single source of truth)', () => {
    const r = resolveFrontendEnv({ DEPLOY_ENV: 'staging' });
    expect(r).toEqual({
      env: 'staging',
      apiUrl: FRONTEND_ENVS.staging.apiUrl,
      cookieDomain: FRONTEND_ENVS.staging.cookieDomain,
      derived: true,
    });
  });

  it('derives from DEPLOY_ENV=production even if explicit vars point elsewhere', () => {
    // DEPLOY_ENV wins: a stray staging BACKEND_URL cannot leak through.
    const r = resolveFrontendEnv({
      DEPLOY_ENV: 'production',
      BACKEND_URL: 'https://api.staging.saplinglearn.com',
      COOKIE_DOMAIN: '.staging.saplinglearn.com',
    });
    expect(r.env).toBe('production');
    expect(r.apiUrl).toBe(FRONTEND_ENVS.production.apiUrl);
    expect(r.cookieDomain).toBe(FRONTEND_ENVS.production.cookieDomain);
    expect(r.derived).toBe(true);
  });

  it('tolerates case/whitespace in DEPLOY_ENV', () => {
    expect(resolveFrontendEnv({ DEPLOY_ENV: '  Staging ' }).env).toBe('staging');
  });

  it('falls back to explicit vars when DEPLOY_ENV is unset (backward compatible)', () => {
    const r = resolveFrontendEnv({
      BACKEND_URL: 'https://api.staging.saplinglearn.com',
      NEXT_PUBLIC_API_URL: 'https://ignored.example.com',
      COOKIE_DOMAIN: '.staging.saplinglearn.com',
    });
    expect(r).toEqual({
      env: null,
      apiUrl: 'https://api.staging.saplinglearn.com', // BACKEND_URL preferred over NEXT_PUBLIC_API_URL
      cookieDomain: '.staging.saplinglearn.com',
      derived: false,
    });
  });

  it('falls back to NEXT_PUBLIC_API_URL when BACKEND_URL is absent', () => {
    const r = resolveFrontendEnv({ NEXT_PUBLIC_API_URL: 'http://backend:5000' });
    expect(r.apiUrl).toBe('http://backend:5000');
    expect(r.derived).toBe(false);
  });

  it('ignores an unknown DEPLOY_ENV and falls back to explicit vars', () => {
    const r = resolveFrontendEnv({ DEPLOY_ENV: 'prod', BACKEND_URL: 'https://api.saplinglearn.com' });
    expect(r.env).toBeNull();
    expect(r.apiUrl).toBe('https://api.saplinglearn.com');
    expect(r.derived).toBe(false);
  });

  it('is empty (no backend) when nothing is configured', () => {
    expect(resolveFrontendEnv({})).toEqual({
      env: null,
      apiUrl: '',
      cookieDomain: undefined,
      derived: false,
    });
  });
});

describe('expectedEnvForHost', () => {
  it('maps the staging host and its subdomains to staging', () => {
    expect(expectedEnvForHost('staging.saplinglearn.com')).toBe('staging');
    expect(expectedEnvForHost('api.staging.saplinglearn.com')).toBe('staging');
  });

  it('maps the apex/www/app prod hosts to production', () => {
    expect(expectedEnvForHost('saplinglearn.com')).toBe('production');
    expect(expectedEnvForHost('www.saplinglearn.com')).toBe('production');
    expect(expectedEnvForHost('app.saplinglearn.com')).toBe('production');
  });

  it('strips a port and is case-insensitive', () => {
    expect(expectedEnvForHost('STAGING.saplinglearn.com:443')).toBe('staging');
  });

  it('returns null for previews / localhost / unknown hosts (no judgment)', () => {
    expect(expectedEnvForHost('foo.workers.dev')).toBeNull();
    expect(expectedEnvForHost('localhost')).toBeNull();
    expect(expectedEnvForHost('')).toBeNull();
    expect(expectedEnvForHost(undefined)).toBeNull();
  });
});

describe('detectHostConfigMismatch', () => {
  it('flags the exact bug: staging host wired to the prod backend', () => {
    const msg = detectHostConfigMismatch(
      'staging.saplinglearn.com',
      'https://api.saplinglearn.com',
    );
    expect(msg).toMatch(/staging/);
    expect(msg).toMatch(/production/);
  });

  it('flags a prod host wired to the staging backend', () => {
    expect(
      detectHostConfigMismatch('www.saplinglearn.com', 'https://api.staging.saplinglearn.com'),
    ).not.toBeNull();
  });

  it('passes when the host and backend agree', () => {
    expect(
      detectHostConfigMismatch('staging.saplinglearn.com', 'https://api.staging.saplinglearn.com'),
    ).toBeNull();
    expect(
      detectHostConfigMismatch('www.saplinglearn.com', 'https://api.saplinglearn.com'),
    ).toBeNull();
  });

  it('does not judge preview hosts or non-canonical backends', () => {
    expect(
      detectHostConfigMismatch('foo.workers.dev', 'https://api.saplinglearn.com'),
    ).toBeNull();
    expect(
      detectHostConfigMismatch('staging.saplinglearn.com', 'http://backend:5000'),
    ).toBeNull();
  });

  // The reported bug: a staging host wired to `https://api.saplinglearn.com/`
  // classified as unknown, so the runtime guard silently did not fire.
  it('flags a trailing-slash prod backend on a staging host', () => {
    const msg = detectHostConfigMismatch(
      'staging.saplinglearn.com',
      'https://api.saplinglearn.com/',
    );
    expect(msg).not.toBeNull();
    expect(msg).toMatch(/production/);
  });

  it('still passes a trailing-slash backend that matches the host', () => {
    expect(
      detectHostConfigMismatch('staging.saplinglearn.com', 'https://api.staging.saplinglearn.com/'),
    ).toBeNull();
  });
});
