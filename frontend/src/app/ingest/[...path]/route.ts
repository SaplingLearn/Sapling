/**
 * `/ingest/*` — same-origin reverse proxy to PostHog US for posthog-js
 * (`api_host: '/ingest'` in src/lib/analytics.ts). Same-origin keeps analytics
 * off third-party-domain blocklists and keeps the browser talking only to us.
 *
 * Implemented as a route handler, not a next.config rewrite, so the upstream
 * request is built from a header allowlist and never carries the student's
 * `sapling_session` cookie or IP — see src/lib/ingestProxy.ts for the full
 * reason. Not an open relay: only the endpoints the SDK config uses, only
 * with a `sapling_session` that verifies (never forwarded), bodies capped at
 * MAX_INGEST_BODY_BYTES, and only events for this deployment's project key.
 */
import {
  MAX_INGEST_BODY_BYTES,
  downstreamResponseHeaders,
  ingestTokens,
  ingestTokensOk,
  isAllowedIngestRequest,
  isImmutableAsset,
  readCappedBody,
  sessionTokenFrom,
  upstreamRequestHeaders,
  upstreamTarget,
} from "@/lib/ingestProxy";
import { verifySession } from "@/lib/sessionToken";

export const dynamic = "force-dynamic";

/** The project key this build sends to — read per request (tests stub it). */
function projectKey(): string {
  return process.env.NEXT_PUBLIC_POSTHOG_KEY ?? "";
}

async function proxy(request: Request): Promise<Response> {
  const { pathname, search } = new URL(request.url);
  const target = upstreamTarget(pathname, search);
  if (!target || !isAllowedIngestRequest(request.method, target.path)) {
    return new Response("Not found", { status: 404 });
  }
  // Not an open relay: analytics only runs for signed-in students, so the
  // session must verify (local HMAC + expiry, as middleware.ts does).
  const token = sessionTokenFrom(request.headers);
  if (!token || !(await verifySession(token))) return new Response(null, { status: 403 });

  const init: RequestInit = {
    method: request.method,
    headers: upstreamRequestHeaders(request.headers),
  };
  if (request.method === "POST") {
    const declared = Number(request.headers.get("content-length") ?? "0");
    if (declared > MAX_INGEST_BODY_BYTES) return new Response(null, { status: 413 });
    const body = await readCappedBody(request.body, MAX_INGEST_BODY_BYTES);
    if (!body) return new Response(null, { status: 413 });
    // …and only into THIS deployment's PostHog project.
    const tokens = ingestTokens(body, search);
    if (tokens === null) return new Response(null, { status: 400 });
    if (!ingestTokensOk(tokens, projectKey())) return new Response(null, { status: 403 });
    init.body = body;
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
