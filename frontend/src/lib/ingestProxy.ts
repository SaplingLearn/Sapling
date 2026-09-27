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
 */

/** PostHog US ingestion + asset hosts. */
export const POSTHOG_INGEST_ORIGIN = "https://us.i.posthog.com";
export const POSTHOG_ASSETS_ORIGIN = "https://us-assets.i.posthog.com";

/** Mount point of the proxy; must match analytics.ts DEFAULT_API_HOST. */
export const INGEST_PREFIX = "/ingest";

/**
 * Map `/ingest/<rest>?<query>` to the PostHog URL. `static/*` and `array/*`
 * (SDK bundles + remote config scripts) live on the assets host; everything
 * else (`/e/`, `/flags/`, `/i/v0/e/`, …) on the ingestion host. The trailing
 * slash PostHog's endpoints use is preserved verbatim.
 */
export function upstreamUrl(pathname: string, search: string): string | null {
  if (!pathname.startsWith(INGEST_PREFIX + "/")) return null;
  const rest = pathname.slice(INGEST_PREFIX.length); // keeps the leading "/"
  // Refuse traversal/odd paths rather than normalise them.
  if (rest.includes("..") || rest.includes("//") || rest.includes("\\")) return null;
  const origin =
    rest.startsWith("/static/") || rest.startsWith("/array/")
      ? POSTHOG_ASSETS_ORIGIN
      : POSTHOG_INGEST_ORIGIN;
  return origin + rest + (search ?? "");
}

/** Request headers worth forwarding. Everything else is dropped. */
const FORWARD_REQUEST_HEADERS = [
  "accept",
  "content-encoding",
  "content-type",
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

export function downstreamResponseHeaders(upstream: Headers): Headers {
  const out = new Headers();
  for (const name of FORWARD_RESPONSE_HEADERS) {
    const v = upstream.get(name);
    if (v !== null) out.set(name, v);
  }
  return out;
}
