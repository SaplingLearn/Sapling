/**
 * Guards the ONE ordering invariant next.config.ts's rewrites have to hold:
 * the backend /api proxy must never shadow a route this app serves itself.
 *
 * The app owns exactly one /api route today — the session BFF at
 * src/app/api/auth/session, the only thing that can mint `sapling_session`.
 * When the proxy sat in `afterFiles` (what returning a bare ARRAY means), Next
 * 16 matched it before that route handler and proxied the request to a backend
 * with no such endpoint, so `POST /api/auth/session` 404'd and every real
 * Google sign-in failed at the last step. `fallback` is checked only after
 * filesystem and dynamic routes have missed (rewrites doc, step 8), so the
 * app's own routes always win.
 *
 * The e2e journey (e2e/auth-session.spec.ts) proves the live behaviour; this
 * catches the config regression without a stack, including for a future BFF
 * route nobody wrote a journey for yet.
 */
import { describe, expect, it } from 'vitest';

import nextConfig from './next.config';

type Rewrite = { source: string; destination: string };
type Rewrites = {
  beforeFiles: Rewrite[];
  afterFiles: Rewrite[];
  fallback: Rewrite[];
};

const isProxy = (r: Rewrite) => /^https?:\/\//.test(r.destination);

async function rewrites(): Promise<Rewrites> {
  const result = await nextConfig.rewrites!();
  // The array form IS the bug: it means `afterFiles`, which outranks the
  // app's own route handlers.
  expect(Array.isArray(result)).toBe(false);
  return result as Rewrites;
}

describe('next.config rewrites', () => {
  it('proxies /api to the backend only in the fallback phase', async () => {
    const { fallback } = await rewrites();
    const proxy = fallback.filter(isProxy);
    expect(proxy.map(r => r.source)).toContain('/api/:path*');
  });

  it('keeps every backend proxy out of beforeFiles and afterFiles', async () => {
    const { beforeFiles, afterFiles } = await rewrites();
    expect(beforeFiles.filter(isProxy)).toEqual([]);
    expect(afterFiles.filter(isProxy)).toEqual([]);
  });

  it('does not try to exempt a local route with a self-rewrite', async () => {
    // `{ source: X, destination: X }` was the old exemption for the session
    // BFF. It does not re-enter route matching — it resolves to not-found —
    // so it 404'd exactly like the proxy it was meant to dodge.
    const all = await rewrites();
    const selfRewrites = [...all.beforeFiles, ...all.afterFiles, ...all.fallback]
      .filter(r => r.source === r.destination);
    expect(selfRewrites).toEqual([]);
  });
});
