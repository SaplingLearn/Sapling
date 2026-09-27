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

/**
 * Mount point of the proxy — the one definition: analytics.ts passes this
 * constant as posthog-js's `api_host`.
 */
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


/**
 * A versioned SDK bundle: posthog-js asks for either the legacy
 * `/ingest/static/<name>.js?v=<lib version>` or (its `'fallback'` default)
 * the semver path `/ingest/static/<lib version>/<name>.js`. Either way the
 * version is in the URL, so a given URL never changes and the browser can
 * keep it for good instead of revalidating every 4 hours (PostHog's own
 * `max-age=14400`). Unversioned files — `static/array.js`,
 * `array/<key>/config.js` — keep PostHog's headers.
 */
export const IMMUTABLE_CACHE_CONTROL = "public, max-age=31536000, immutable";

const SEMVER_STATIC = /^\/static\/\d+\.\d+\.\d+[^/]*\/[^/]+$/;

/** `path` is an already-normalised path from upstreamTarget. */
export function isImmutableAsset(path: string, search: string): boolean {
  if (!path.startsWith("/static/")) return false;
  return SEMVER_STATIC.test(path) || new URLSearchParams(search).has("v");
}

// ── guards: this is not an open relay ───────────────────────────────────────

/**
 * Exactly the endpoints the SDK config in src/lib/analytics.ts uses.
 * Events go to `/e/` (or `/i/v0/e/`, `/batch/` in other SDK versions) by
 * POST; lazily loaded SDK bundles come from `/static/` by GET/HEAD. Flags,
 * remote config (`/array/…`, `/flags/`, `/decide/`) and session recording
 * (`/s/`) are disabled in that config, so they are refused here too.
 */
const EVENT_PATHS = new Set(["/e/", "/i/v0/e/", "/batch/"]);
const STATIC_PATH = /^\/static\/(?:\d+\.\d+\.\d+[^/]*\/)?[A-Za-z0-9._-]+\.js$/;

export function isAllowedIngestRequest(method: string, path: string): boolean {
  if (EVENT_PATHS.has(path)) return method === "POST";
  if (STATIC_PATH.test(path)) return method === "GET" || method === "HEAD";
  return false;
}

/**
 * Analytics only ever runs for a signed-in student, so a caller must present
 * a VALID `sapling_session`: the route checks it with `verifySession()`
 * (src/lib/sessionToken.ts) — the same local HMAC + expiry check
 * middleware.ts runs, no backend call. The cookie is never forwarded — see
 * upstreamRequestHeaders.
 */
export const SESSION_COOKIE_NAME = "sapling_session";

/** The raw `sapling_session` cookie value, or null. */
export function sessionTokenFrom(headers: Headers): string | null {
  const cookie = headers.get("cookie") ?? "";
  for (const part of cookie.split(";")) {
    const [name, ...rest] = part.trim().split("=");
    if (name === SESSION_COOKIE_NAME) {
      const value = rest.join("=");
      return value.length > 0 ? value : null;
    }
  }
  return null;
}

/** Largest request body forwarded upstream; a posthog-js request is far smaller. */
export const MAX_INGEST_BODY_BYTES = 1024 * 1024;

/**
 * Read a request body into memory, refusing (null) as soon as it passes
 * `max` bytes — so a chunked body with no Content-Length is capped too. The
 * body is buffered rather than streamed because its project key has to be
 * checked (ingestTokensOk) before anything goes upstream; the cap bounds it.
 */
export async function readCappedBody(
  body: ReadableStream<Uint8Array> | null,
  max: number,
): Promise<Uint8Array<ArrayBuffer> | null> {
  if (!body) return new Uint8Array(new ArrayBuffer(0));
  const reader = body.getReader();
  const chunks: Uint8Array[] = [];
  let seen = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    seen += value.byteLength;
    if (seen > max) {
      await reader.cancel().catch(() => {});
      return null;
    }
    chunks.push(value);
  }
  const out = new Uint8Array(new ArrayBuffer(seen));
  let at = 0;
  for (const c of chunks) {
    out.set(c, at);
    at += c.byteLength;
  }
  return out;
}

/**
 * The project keys an event/batch body names, or null when the body is not
 * in a form this proxy accepts. posthog-js is configured with
 * `disable_compression` (src/lib/analytics.ts), so a body is one of:
 * - JSON (`application/json`): a batch `{ api_key, batch: [...] }`, a single
 *   event `{ event, properties: { token } }`, or an array of events;
 * - `data=<base64 JSON>` (`application/x-www-form-urlencoded`): what
 *   posthog-js always uses for `sendBeacon` (e.g. `$pageleave`).
 * A gzip body (`compression=gzip-js`) is refused rather than decompressed:
 * posthog-js never sends one with this config, and not decompressing
 * attacker-supplied input keeps the 1 MiB cap a real bound.
 */
export function ingestTokens(body: Uint8Array, search: string): string[] | null {
  const compression = new URLSearchParams(search).get("compression");
  if (compression && compression !== "base64") return null;
  let text: string;
  try {
    text = new TextDecoder("utf-8", { fatal: true }).decode(body);
    if (text.startsWith("data=")) {
      const b64 = decodeURIComponent(text.slice("data=".length).replace(/\+/g, " "));
      const bin = atob(b64);
      text = new TextDecoder("utf-8", { fatal: true }).decode(
        Uint8Array.from(bin, (c) => c.charCodeAt(0)),
      );
    }
  } catch {
    return null;
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return null;
  }
  const tokens: string[] = [];
  const visit = (node: unknown, depth: number): void => {
    if (depth > 2 || node === null || typeof node !== "object") return;
    if (Array.isArray(node)) {
      for (const item of node) visit(item, depth + 1);
      return;
    }
    const obj = node as Record<string, unknown>;
    for (const key of ["api_key", "token"]) if (typeof obj[key] === "string") tokens.push(obj[key] as string);
    const props = obj.properties as Record<string, unknown> | undefined;
    if (props && typeof props.token === "string") tokens.push(props.token);
    if (Array.isArray(obj.batch)) visit(obj.batch, depth + 1);
  };
  visit(parsed, 0);
  return tokens;
}

/** Every key the body names is this deployment's project key — and there is one. */
export function ingestTokensOk(tokens: string[] | null, projectKey: string): boolean {
  const key = projectKey.trim();
  return !!key && tokens !== null && tokens.length > 0 && tokens.every((t) => t === key);
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
