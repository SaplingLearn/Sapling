/**
 * `/ingest/*` — same-origin reverse proxy to PostHog US for posthog-js
 * (`api_host: '/ingest'` in src/lib/analytics.ts). Same-origin keeps analytics
 * off third-party-domain blocklists and keeps the browser talking only to us.
 *
 * Implemented as a route handler, not a next.config rewrite, so the upstream
 * request is built from a header allowlist and never carries the student's
 * `sapling_session` cookie or IP — see src/lib/ingestProxy.ts for the full
 * reason. Not an open relay: only the endpoints the SDK config uses, only
 * with a `sapling_session` cookie present (checked, never forwarded), and
 * bodies capped at MAX_INGEST_BODY_BYTES.
 */
import {
  MAX_INGEST_BODY_BYTES,
  capStream,
  downstreamResponseHeaders,
  hasSessionCookie,
  isAllowedIngestRequest,
  isImmutableAsset,
  upstreamRequestHeaders,
  upstreamTarget,
} from "@/lib/ingestProxy";

export const dynamic = "force-dynamic";

/** `duplex` is required by fetch() for a streamed body but missing from lib.dom. */
type StreamingRequestInit = RequestInit & { duplex?: "half" };

async function proxy(request: Request): Promise<Response> {
  const { pathname, search } = new URL(request.url);
  const target = upstreamTarget(pathname, search);
  if (!target || !isAllowedIngestRequest(request.method, target.path)) {
    return new Response("Not found", { status: 404 });
  }
  // Not an open relay: analytics only runs for signed-in students.
  if (!hasSessionCookie(request.headers)) return new Response(null, { status: 403 });

  const init: StreamingRequestInit = {
    method: request.method,
    headers: upstreamRequestHeaders(request.headers),
  };
  let overLimit = false;
  if (request.method !== "GET" && request.method !== "HEAD" && request.body) {
    const declared = Number(request.headers.get("content-length") ?? "0");
    if (declared > MAX_INGEST_BODY_BYTES) return new Response(null, { status: 413 });
    // Stream the batch through instead of buffering it in the Worker, with a
    // running byte count for a body that declares no (or a false) length.
    init.body = capStream(request.body, MAX_INGEST_BODY_BYTES, () => {
      overLimit = true;
    });
    init.duplex = "half";
  }

  let upstream: Response;
  try {
    upstream = await fetch(target.url, init);
  } catch {
    if (overLimit) return new Response(null, { status: 413 });
    // Analytics is best-effort: a PostHog outage must look like a dropped
    // batch to the SDK, not an app error.
    return new Response(null, { status: 502 });
  }

  // A 304 revalidation of a versioned bundle is just as immutable as the 200.
  const immutable =
    (upstream.ok || upstream.status === 304) && isImmutableAsset(target.path, search);
  return new Response(request.method === "HEAD" ? null : upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: downstreamResponseHeaders(upstream.headers, { immutable }),
  });
}

export const GET = proxy;
export const HEAD = proxy;
export const POST = proxy;
