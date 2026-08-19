/**
 * Fail-loud guard against the "staging config on the prod worker" footgun.
 *
 * The prod `frontend` Cloudflare Workers Build's deploy step was set to
 * `npx wrangler deploy --env staging`, which applied wrangler.toml's
 * `[env.staging.vars]` — staging API URLs and a `.staging.saplinglearn.com`
 * cookie domain — to the PROD worker (wrangler even warned it overrode the
 * worker name from "frontend-staging" back to "frontend"). Sign-in then broke
 * on saplinglearn.com: the middleware routed auth to the staging backend and
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
    siteUrl: 'https://saplinglearn.com',
  },
  staging: {
    apiUrl: 'https://api.staging.saplinglearn.com',
    cookieDomain: '.staging.saplinglearn.com',
    siteUrl: 'https://staging.saplinglearn.com',
  },
} as const;

export type FrontendEnv = keyof typeof FRONTEND_ENVS;

// Reads NEXT_PUBLIC_API_URL, BACKEND_URL, COOKIE_DOMAIN and DEPLOY_ENV. Typed as
// a plain record so both `process.env` (index-signature only) and test fixtures
// are accepted.
type EnvSource = Readonly<Record<string, string | undefined>>;

/**
 * Match a value to a known environment, or null (empty / non-canonical).
 *
 * URL fields are compared with any trailing slashes stripped: `https://api.
 * saplinglearn.com/` is the same origin as `https://api.saplinglearn.com`, and
 * treating the slashed spelling as "unknown" silently disarms both guards —
 * checkFrontendDeployEnv() stops seeing the value at all, and
 * detectHostConfigMismatch() returns null for a staging host genuinely wired to
 * the prod backend. A guard that goes quiet on a valid spelling is worse than
 * no guard.
 *
 * cookieDomain is NOT normalised: it is a `Domain` attribute, not a URL, and a
 * trailing slash in it is a real misconfiguration we want left unrecognised.
 */
function classify(
  value: string | undefined,
  field: 'apiUrl' | 'cookieDomain' | 'siteUrl',
): FrontendEnv | null {
  const isUrl = field !== 'cookieDomain';
  const normalise = (s: string) => (isUrl ? s.replace(/\/+$/, '') : s);
  const v = normalise((value ?? '').trim().toLowerCase());
  if (!v) return null;
  for (const env of Object.keys(FRONTEND_ENVS) as FrontendEnv[]) {
    if (normalise(FRONTEND_ENVS[env][field].toLowerCase()) === v) return env;
  }
  // Non-canonical (e.g. a *.workers.dev preview URL): not this guard's call to reject.
  return null;
}

/** The build- and run-time frontend config, resolved from a single knob. */
export interface ResolvedFrontendEnv {
  /** The environment we resolved to, or null (unknown / local / preview). */
  env: FrontendEnv | null;
  /** Backend origin (used for BACKEND_URL and NEXT_PUBLIC_API_URL). */
  apiUrl: string;
  /** Cookie `Domain` attribute, or undefined for a host-only cookie. */
  cookieDomain: string | undefined;
  /** True when values came from DEPLOY_ENV, not explicit env vars. */
  derived: boolean;
}

/**
 * Resolve the effective frontend config from an env bag.
 *
 * `DEPLOY_ENV` is the single source of truth: when it names a known environment
 * the API origin and cookie domain are DERIVED from `FRONTEND_ENVS`, so they
 * cannot drift, be half-set, or be leaked from a stray explicit var. When
 * `DEPLOY_ENV` is unset (local/dev, docker, or a legacy build that sets the
 * vars explicitly) this falls back to the explicit env vars — preserving prior
 * behaviour, including the middleware's `BACKEND_URL`-before-`NEXT_PUBLIC_API_URL`
 * preference (BACKEND_URL is the server-reachable origin; see middleware.ts).
 */
export function resolveFrontendEnv(env: EnvSource): ResolvedFrontendEnv {
  const deployEnv = (env.DEPLOY_ENV ?? '').trim().toLowerCase();
  if (deployEnv && deployEnv in FRONTEND_ENVS) {
    const c = FRONTEND_ENVS[deployEnv as FrontendEnv];
    return { env: deployEnv as FrontendEnv, apiUrl: c.apiUrl, cookieDomain: c.cookieDomain, derived: true };
  }
  return {
    env: null,
    apiUrl: (env.BACKEND_URL ?? '').trim() || (env.NEXT_PUBLIC_API_URL ?? '').trim(),
    cookieDomain: (env.COOKIE_DOMAIN ?? '').trim() || undefined,
    derived: false,
  };
}

/**
 * The canonical public origin for metadata (metadataBase, sitemap, robots).
 * ADR-0022 precedence, same as `resolveFrontendEnv`: when `DEPLOY_ENV` names
 * a known environment it WINS unconditionally — an explicit var must never
 * silently override the environment the build was deployed as.
 * `NEXT_PUBLIC_SITE_URL` is the fallback for local/preview builds where
 * `DEPLOY_ENV` is unset. Defaults to production so crawlers scraping an
 * unconfigured build never index a non-canonical host.
 */
export function resolveSiteUrl(env: EnvSource): string {
  const deployEnv = (env.DEPLOY_ENV ?? '').trim().toLowerCase();
  if (deployEnv && deployEnv in FRONTEND_ENVS) {
    return FRONTEND_ENVS[deployEnv as FrontendEnv].siteUrl;
  }
  const explicit = (env.NEXT_PUBLIC_SITE_URL ?? '').trim();
  if (explicit) return explicit.replace(/\/+$/, '');
  return FRONTEND_ENVS.production.siteUrl;
}

/**
 * Best-effort: which environment SHOULD serve this request host? Returns null
 * for hosts we don't recognise (preview `*.workers.dev`, localhost, custom
 * domains) — the guard must not judge those.
 */
export function expectedEnvForHost(host: string | undefined | null): FrontendEnv | null {
  const h = (host ?? '').trim().toLowerCase().split(':')[0];
  if (!h) return null;
  if (h === 'staging.saplinglearn.com' || h.endsWith('.staging.saplinglearn.com')) return 'staging';
  if (h === 'saplinglearn.com' || h === 'www.saplinglearn.com' || h === 'app.saplinglearn.com') {
    return 'production';
  }
  return null;
}

/**
 * Detect a host/backend mismatch: the worker is serving a host that belongs to
 * one environment but is wired to another environment's backend (the exact
 * failure behind staging's `session_expired` — a prod-config worker answering
 * `staging.saplinglearn.com`). Returns a human-readable reason, or null when
 * consistent or indeterminable. Runtime defence-in-depth for what the
 * build-time guard cannot see (an internally-consistent build shipped to the
 * wrong worker/route).
 */
export function detectHostConfigMismatch(
  host: string | undefined | null,
  effectiveApiUrl: string,
): string | null {
  const expected = expectedEnvForHost(host);
  if (!expected) return null;
  const configured = classify(effectiveApiUrl, 'apiUrl');
  if (!configured || configured === expected) return null;
  return (
    `host ${host} expects the ${expected} backend (${FRONTEND_ENVS[expected].apiUrl}) ` +
    `but is wired to the ${configured} backend (${effectiveApiUrl})`
  );
}

/**
 * Check the frontend deploy variables. Returns a list of problems (empty = OK).
 * Pure — takes an env bag so it is unit-testable.
 */
export function checkFrontendDeployEnv(env: EnvSource): string[] {
  const problems: string[] = [];

  const classified: Partial<
    Record<
      'NEXT_PUBLIC_API_URL' | 'BACKEND_URL' | 'COOKIE_DOMAIN' | 'NEXT_PUBLIC_SITE_URL',
      FrontendEnv
    >
  > = {};
  const api = classify(env.NEXT_PUBLIC_API_URL, 'apiUrl');
  const backend = classify(env.BACKEND_URL, 'apiUrl');
  const cookie = classify(env.COOKIE_DOMAIN, 'cookieDomain');
  const site = classify(env.NEXT_PUBLIC_SITE_URL, 'siteUrl');
  if (api) classified.NEXT_PUBLIC_API_URL = api;
  if (backend) classified.BACKEND_URL = backend;
  if (cookie) classified.COOKIE_DOMAIN = cookie;
  if (site) classified.NEXT_PUBLIC_SITE_URL = site;

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
