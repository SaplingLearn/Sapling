/**
 * `/ingest/*` — same-origin reverse proxy to PostHog US for posthog-js
 * (`api_host: '/ingest'` in src/lib/analytics.ts). Same-origin keeps analytics
 * off third-party-domain blocklists and keeps the browser talking only to us.
 *
 * Implemented as a route handler, not a next.config rewrite, so the upstream
 * request is built from a header allowlist and never carries the student's
 * `sapling_session` cookie or IP — see src/lib/ingestProxy.ts for the full
 * reason. Not in middleware.ts's matcher, so no session check runs here (and
 * none is needed: nothing user-scoped is served).
 */
import {
  downstreamResponseHeaders,
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
  if (!target) return new Response("Not found", { status: 404 });

  const init: StreamingRequestInit = {
    method: request.method,
    headers: upstreamRequestHeaders(request.headers),
  };
  if (request.method !== "GET" && request.method !== "HEAD" && request.body) {
    // Stream the batch through instead of buffering it in the Worker.
    init.body = request.body;
    init.duplex = "half";
  }

  let upstream: Response;
  try {
    upstream = await fetch(target.url, init);
  } catch {
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
