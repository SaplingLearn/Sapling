/**
 * `/ingest/*` — same-origin reverse proxy to PostHog US for posthog-js
 * (`api_host: '/ingest'` in src/lib/analytics.ts). Same-origin keeps analytics
 * off third-party-domain blocklists and keeps the browser talking only to us.
 *
 * Implemented as a route handler, not a next.config rewrite, so the upstream
 * request is built from a header allowlist and never carries the student's
 * `sapling_session` cookie — see src/lib/ingestProxy.ts for the full reason.
 * Not in middleware.ts's matcher, so no session check runs here (and none is
 * needed: nothing user-scoped is served).
 */
import {
  downstreamResponseHeaders,
  upstreamRequestHeaders,
  upstreamUrl,
} from "@/lib/ingestProxy";

export const dynamic = "force-dynamic";

async function proxy(request: Request): Promise<Response> {
  const { pathname, search } = new URL(request.url);
  const target = upstreamUrl(pathname, search);
  if (!target) return new Response("Not found", { status: 404 });

  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers: upstreamRequestHeaders(request.headers),
      body: hasBody ? await request.arrayBuffer() : undefined,
    });
  } catch {
    // Analytics is best-effort: a PostHog outage must look like a dropped
    // batch to the SDK, not an app error.
    return new Response(null, { status: 502 });
  }

  return new Response(request.method === "HEAD" ? null : upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: downstreamResponseHeaders(upstream.headers),
  });
}

export const GET = proxy;
export const HEAD = proxy;
export const POST = proxy;
