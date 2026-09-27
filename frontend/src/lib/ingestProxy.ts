/**
 * The same-origin PostHog reverse proxy behind `/ingest/*` (see
 * src/app/ingest/[...path]/route.ts). Pure so it is unit-testable.
 *
 * Why a route handler rather than the `next.config.ts` rewrites PostHog's
 * Next.js guide suggests: under @opennextjs/cloudflare an external rewrite is
 * proxied by OpenNext's fetch proxy, which forwards EVERY incoming request
 * header upstream — including `Cookie`. Every `/ingest` request from a signed-in
 * browser carries the HttpOnly `sapling_session` token (scoped to `/` on the
 * app's domain), so a rewrite would hand each student's live session
 * credential to a third party on every analytics batch. Here the upstream
 * request is built from an allowlist instead: no cookies, no auth, no
 * client-IP headers, and the Host comes from the upstream URL.
 *
 * The client IP is withheld ON PURPOSE (not forwarded as `X-Forwarded-For`,
 * never `cf-connecting-ip`): PostHog sees the Worker's egress address, so its
 * `$ip` and any GeoIP it derived would describe Cloudflare, not the student.
 * posthog-js sends `$geoip_disable` on every event (src/lib/analytics.ts) and
 * the project runs with "Discard client IP data" on, so neither is kept.
 */

/** PostHog US ingestion + asset hosts. */
export const POSTHOG_INGEST_ORIGIN = "https://us.i.posthog.com";
export const POSTHOG_ASSETS_ORIGIN = "https://us-assets.i.posthog.com";

/** Mount point of the proxy; must match analytics.ts DEFAULT_API_HOST. */
export const INGEST_PREFIX = "/ingest";

/**
 * Every PostHog path is plain unreserved characters in non-empty segments,
 * with an optional trailing slash (`/e/`, `/flags/`, `/i/v0/e/`,
 * `/static/array.js`, `/array/phc_…/config.js`).
 */
const SAFE_REST = /^(?:\/[A-Za-z0-9._~-]+)+\/?$/;

/**
 * The path below `/ingest`, decoded and checked, or null to refuse it.
 *
 * Refused rather than normalised: a percent-encoded dot, slash, backslash or
 * percent (`%2e%2e`, `%2F`, `%5c`, `%25` — any case) is checked on the RAW
 * path, before decoding, because no real PostHog path contains one and an
 * upstream that decodes it would read `/static/%2e%2e%2fflags` as `/flags`.
 * After decoding, anything outside SAFE_REST and any `.`/`..` segment is
 * refused too. The result is what both host routing and the upstream URL are
 * built from, so the two can never disagree about which path is meant.
 */
export function normalisedIngestPath(pathname: string): string | null {
  if (!pathname.startsWith(INGEST_PREFIX + "/")) return null;
  const raw = pathname.slice(INGEST_PREFIX.length); // keeps the leading "/"
  if (/%(?:2e|2f|5c|25)/i.test(raw)) return null;
  let rest: string;
  try {
    rest = decodeURIComponent(raw);
  } catch {
    return null; // malformed escape
  }
  if (!SAFE_REST.test(rest)) return null;
  if (rest.split("/").some((seg) => seg === "." || seg === "..")) return null;
  return rest;
}

/** `static/*` and `array/*` (SDK bundles, remote config) live on the assets host. */
function isAssetPath(rest: string): boolean {
  return rest.startsWith("/static/") || rest.startsWith("/array/");
}

/** Where one `/ingest` request goes: the PostHog URL + the checked path. */
export interface IngestTarget {
  /** The full upstream URL, query included. */
  url: string;
  /** The normalised path below `/ingest` (normalisedIngestPath). */
  path: string;
}

/**
 * Map `/ingest/<rest>?<query>` to the PostHog URL. `static/*` and `array/*`
 * go to the assets host; everything else (`/e/`, `/flags/`, `/i/v0/e/`, …) to
 * the ingestion host. The trailing slash PostHog's endpoints use is kept.
 * The path is validated here, once; callers reuse `path` from the result.
 */
export function upstreamTarget(pathname: string, search: string): IngestTarget | null {
  const rest = normalisedIngestPath(pathname);
  if (rest === null) return null;
  const origin = isAssetPath(rest) ? POSTHOG_ASSETS_ORIGIN : POSTHOG_INGEST_ORIGIN;
  const target = new URL(origin + rest + (search ?? ""));
  // Belt and braces: the URL parser must agree the path stayed put on that host.
  if (target.origin !== origin || target.pathname !== rest) return null;
  return { url: target.toString(), path: rest };
}

/** Convenience: just the upstream URL, or null to refuse. */
export function upstreamUrl(pathname: string, search: string): string | null {
  return upstreamTarget(pathname, search)?.url ?? null;
}

/**
 * A versioned SDK bundle (`/ingest/static/<name>.js?v=<lib version>`):
 * posthog-js puts its own version in the query, so a given URL never changes
 * and the browser can keep it for good instead of revalidating every 4 hours
 * (PostHog's own `max-age=14400`). Unversioned files — `static/array.js`,
 * `array/<key>/config.js` — keep PostHog's headers.
 */
export const IMMUTABLE_CACHE_CONTROL = "public, max-age=31536000, immutable";

/** `path` is an already-normalised path from upstreamTarget. */
export function isImmutableAsset(path: string, search: string): boolean {
  return path.startsWith("/static/") && new URLSearchParams(search).has("v");
}

/**
 * Request headers worth forwarding. Everything else is dropped. The two
 * conditional headers let a browser revalidating a cached SDK bundle get a
 * 304 from PostHog instead of the whole file again.
 */
const FORWARD_REQUEST_HEADERS = [
  "accept",
  "content-encoding",
  "content-type",
  "if-modified-since",
  "if-none-match",
  "user-agent",
] as const;

export function upstreamRequestHeaders(incoming: Headers): Headers {
  const out = new Headers();
  for (const name of FORWARD_REQUEST_HEADERS) {
    const v = incoming.get(name);
    if (v !== null) out.set(name, v);
  }
  return out;
}

/**
 * Response headers passed back to the browser. `content-encoding` and
 * `content-length` are deliberately absent: fetch() hands us a DECODED body,
 * so echoing the upstream encoding would make the browser try to gunzip
 * plain bytes. `set-cookie` is absent so PostHog can never set a cookie on
 * the app's domain.
 */
const FORWARD_RESPONSE_HEADERS = [
  "cache-control",
  "content-type",
  "etag",
  "last-modified",
  "vary",
] as const;

export function downstreamResponseHeaders(
  upstream: Headers,
  opts: { immutable?: boolean } = {},
): Headers {
  const out = new Headers();
  for (const name of FORWARD_RESPONSE_HEADERS) {
    const v = upstream.get(name);
    if (v !== null) out.set(name, v);
  }
  if (opts.immutable) out.set("cache-control", IMMUTABLE_CACHE_CONTROL);
  return out;
}
