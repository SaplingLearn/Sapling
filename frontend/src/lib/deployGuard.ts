/**
 * Fail-loud guard against the "staging config on the prod worker" footgun.
 *
 * The prod `frontend` Cloudflare Workers Build's deploy step was set to
 * `npx wrangler deploy --env staging`, which applied wrangler.toml's
 * `[env.staging.vars]` — staging API URLs and a `.staging.saplinglearn.com`
 * cookie domain — to the PROD worker (wrangler even warned it overrode the
 * worker name from "frontend-staging" back to "frontend"). Sign-in then broke
 * on saplinglearn.com: the proxy routed auth to the staging backend and
 * the `sapling_session` cookie was scoped to `.staging`, so it never stuck.
 *
 * NEXT_PUBLIC_API_URL is inlined and the `/api` rewrite bakes BACKEND_URL at
 * BUILD time — wrangler.toml `[vars]` are runtime-only and can't fix a bad
 * build after the fact. This guard runs during `next build` and turns the
 * silent environment mixup into a hard failure.
 */

export const FRONTEND_ENVS = {
  production: {
    apiUrl: 'https://api.saplinglearn.com',
    cookieDomain: '.saplinglearn.com',
  },
  staging: {
    apiUrl: 'https://api.staging.saplinglearn.com',
    cookieDomain: '.staging.saplinglearn.com',
  },
} as const;

export type FrontendEnv = keyof typeof FRONTEND_ENVS;

// Reads NEXT_PUBLIC_API_URL, BACKEND_URL, COOKIE_DOMAIN and DEPLOY_ENV. Typed as
// a plain record so both `process.env` (index-signature only) and test fixtures
// are accepted.
type EnvSource = Readonly<Record<string, string | undefined>>;

/** Match a value to a known environment, or null (empty / non-canonical). */
function classify(
  value: string | undefined,
  field: 'apiUrl' | 'cookieDomain',
): FrontendEnv | null {
  const v = (value ?? '').trim().toLowerCase();
  if (!v) return null;
  for (const env of Object.keys(FRONTEND_ENVS) as FrontendEnv[]) {
    if (FRONTEND_ENVS[env][field].toLowerCase() === v) return env;
  }
  // Non-canonical (e.g. a *.workers.dev preview URL): not this guard's call to reject.
  return null;
}

/**
 * Check the frontend deploy variables. Returns a list of problems (empty = OK).
 * Pure — takes an env bag so it is unit-testable.
 */
export function checkFrontendDeployEnv(env: EnvSource): string[] {
  const problems: string[] = [];

  const classified: Partial<
    Record<'NEXT_PUBLIC_API_URL' | 'BACKEND_URL' | 'COOKIE_DOMAIN', FrontendEnv>
  > = {};
  const api = classify(env.NEXT_PUBLIC_API_URL, 'apiUrl');
  const backend = classify(env.BACKEND_URL, 'apiUrl');
  const cookie = classify(env.COOKIE_DOMAIN, 'cookieDomain');
  if (api) classified.NEXT_PUBLIC_API_URL = api;
  if (backend) classified.BACKEND_URL = backend;
  if (cookie) classified.COOKIE_DOMAIN = cookie;

  // 1. Consistency (always on, no config needed): every canonical value must
  //    name the SAME environment. Catches split-brain like a prod API URL with
  //    a `.staging` cookie domain.
  const distinct = new Set(Object.values(classified));
  if (distinct.size > 1) {
    const detail = Object.entries(classified)
      .map(([k, v]) => `${k}→${v}`)
      .join(', ');
    problems.push(
      `deploy variables mix environments (${detail}); NEXT_PUBLIC_API_URL, BACKEND_URL ` +
        'and COOKIE_DOMAIN must all target one environment',
    );
  }

  // 2. Explicit lock (opt-in via DEPLOY_ENV): every canonical value must match
  //    the named environment. This is what catches an all-staging build shipped
  //    to the prod worker — the exact bug — which check #1 alone cannot see
  //    (all-staging is internally consistent). Set DEPLOY_ENV=production on the
  //    prod Workers Build and DEPLOY_ENV=staging on the staging one.
  const deployEnv = (env.DEPLOY_ENV ?? '').trim().toLowerCase();
  if (deployEnv) {
    if (!(deployEnv in FRONTEND_ENVS)) {
      problems.push(
        `DEPLOY_ENV must be one of ${Object.keys(FRONTEND_ENVS).join(' | ')}, ` +
          `got ${JSON.stringify(env.DEPLOY_ENV)}`,
      );
    } else {
      const want = FRONTEND_ENVS[deployEnv as FrontendEnv];
      const mismatched = Object.entries(classified).filter(([, v]) => v !== deployEnv);
      if (mismatched.length) {
        const detail = mismatched.map(([k, v]) => `${k}→${v}`).join(', ');
        problems.push(
          `DEPLOY_ENV=${deployEnv} but ${detail} point elsewhere; expected ` +
            `NEXT_PUBLIC_API_URL/BACKEND_URL=${want.apiUrl}, COOKIE_DOMAIN=${want.cookieDomain}`,
        );
      }
    }
  }

  return problems;
}
