import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'
import { verifySession } from '@/lib/sessionToken'
import { resolveFrontendEnv, detectHostConfigMismatch } from '@/lib/deployGuard'

// Every route in the (shell) group is gated here. #189: /profile/[userId]
// was the one shell route missing from both this list and config.matcher, so
// the middleware never ran there and an unauthenticated visitor could
// enumerate /profile/<any-id>. Gate it consistently with its siblings.
const PROTECTED = [
  '/dashboard', '/learn', '/quiz', '/study', '/tree',
  '/library', '/calendar', '/social',
  '/settings', '/achievements', '/admin',
  '/gradebook', '/course-planner', '/notetaker', '/profile'
]

// This middleware runs on the SERVER, so it needs an origin reachable from the
// server — which is not always the browser-facing one. Under docker compose the
// backend is http://backend:5000 on the compose network but http://localhost:5000
// from the host browser, so NEXT_PUBLIC_API_URL (inlined for the browser) is not
// resolvable here. BACKEND_URL is the server-side origin and is preferred.
// In prod/staging the two are identical (frontend/wrangler.toml) so this is a
// no-op there; the NEXT_PUBLIC_API_URL fallback keeps any env that only sets
// that one working. .trim() mirrors next.config.ts's defense against a stray
// space in a deploy variable.
//
// DEPLOY_ENV is the single source of truth: when set (wrangler.toml `[vars]` /
// `[env.staging.vars]`) the backend origin is derived from FRONTEND_ENVS so it
// cannot drift from the deployed environment. When unset (docker/local) it
// falls back to BACKEND_URL, then NEXT_PUBLIC_API_URL — the original behaviour.
const RESOLVED = resolveFrontendEnv(process.env as Record<string, string | undefined>)
const API_URL = RESOLVED.apiUrl

function googleAuthRedirect() {
  if (!API_URL) return null
  return new URL('/api/auth/google', API_URL).toString()
}

function redirectToSignin(request: NextRequest, errorCode?: string) {
  const g = googleAuthRedirect()
  if (g && !errorCode) return NextResponse.redirect(g)
  const u = new URL('/', request.url)
  if (errorCode) u.searchParams.set('error', errorCode)
  return NextResponse.redirect(u)
}

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl

  const isProtected = PROTECTED.some(p => pathname.startsWith(p))
  if (!isProtected) return NextResponse.next()

  // Defence-in-depth for the "wrong environment on this worker" deploy footgun:
  // if the host we're serving belongs to one environment (e.g. staging.*) but
  // API_URL points at another's backend (e.g. prod api.*), sign-in silently
  // fails — the backend can't validate a session cookie signed with the other
  // env's SESSION_SECRET, which surfaced as a mystery `session_expired` on
  // staging. Fail with a distinct, greppable code and a loud server log instead.
  const mismatch = detectHostConfigMismatch(request.nextUrl.hostname, API_URL)
  if (mismatch) {
    console.error(
      `[sapling] deploy misconfiguration: ${mismatch}. This worker is serving the ` +
        'wrong environment — redeploy with the correct DEPLOY_ENV build variable and ' +
        '`wrangler deploy --env <env>`, and confirm the custom-domain route binding. ' +
        'See docs/decisions/0022-deploy-env-single-source-of-truth.md.',
    )
    return redirectToSignin(request, 'env_misconfig')
  }

  const token = request.cookies.get('sapling_session')?.value
  if (!token) return redirectToSignin(request)

  const session = await verifySession(token)
  if (!session) return redirectToSignin(request, 'session_expired')

  if (!API_URL) return redirectToSignin(request, 'google_not_configured')
  try {
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 3000)
    let res: Response
    try {
      res = await fetch(
        `${API_URL}/api/auth/me?user_id=${encodeURIComponent(session.userId)}`,
        { signal: controller.signal, headers: { Cookie: `sapling_session=${token}` } },
      )
    } finally {
      clearTimeout(timeout)
    }
    if (!res.ok) return redirectToSignin(request, 'session_expired')
    const data = await res.json()
    if (data.is_approved !== true) return NextResponse.redirect(new URL('/pending', request.url))
  } catch {
    return redirectToSignin(request, 'signin_failed')
  }

  return NextResponse.next()
}

// Router prefetches are excluded. Every <Link> in the side nav is prefetched
// in production, and each prefetch used to run this whole function — including
// the /api/auth/me round trip (4–9 DB reads) — so a cold shell load cost ~35-40
// backend calls before the page did anything. Skipping them is safe: these
// routes are static shells with no user data in the payload, the document
// request and every non-prefetch navigation still run the gate, and the APIs
// authenticate every call themselves. An unapproved user never holds a session
// (auth.py issues none), so the approval check above is not a security boundary.
// The matcher must be a static literal — Next parses it at build time, so the
// `missing` list is repeated rather than shared through a constant.
export const config = {
  matcher: [
    { source: '/dashboard/:path*', missing: [{ type: 'header', key: 'next-router-prefetch' }, { type: 'header', key: 'purpose', value: 'prefetch' }] },
    { source: '/learn/:path*', missing: [{ type: 'header', key: 'next-router-prefetch' }, { type: 'header', key: 'purpose', value: 'prefetch' }] },
    { source: '/quiz/:path*', missing: [{ type: 'header', key: 'next-router-prefetch' }, { type: 'header', key: 'purpose', value: 'prefetch' }] },
    { source: '/study/:path*', missing: [{ type: 'header', key: 'next-router-prefetch' }, { type: 'header', key: 'purpose', value: 'prefetch' }] },
    { source: '/tree/:path*', missing: [{ type: 'header', key: 'next-router-prefetch' }, { type: 'header', key: 'purpose', value: 'prefetch' }] },
    { source: '/library/:path*', missing: [{ type: 'header', key: 'next-router-prefetch' }, { type: 'header', key: 'purpose', value: 'prefetch' }] },
    { source: '/calendar/:path*', missing: [{ type: 'header', key: 'next-router-prefetch' }, { type: 'header', key: 'purpose', value: 'prefetch' }] },
    { source: '/social/:path*', missing: [{ type: 'header', key: 'next-router-prefetch' }, { type: 'header', key: 'purpose', value: 'prefetch' }] },
    { source: '/settings/:path*', missing: [{ type: 'header', key: 'next-router-prefetch' }, { type: 'header', key: 'purpose', value: 'prefetch' }] },
    { source: '/achievements/:path*', missing: [{ type: 'header', key: 'next-router-prefetch' }, { type: 'header', key: 'purpose', value: 'prefetch' }] },
    { source: '/admin/:path*', missing: [{ type: 'header', key: 'next-router-prefetch' }, { type: 'header', key: 'purpose', value: 'prefetch' }] },
    { source: '/gradebook/:path*', missing: [{ type: 'header', key: 'next-router-prefetch' }, { type: 'header', key: 'purpose', value: 'prefetch' }] },
    { source: '/course-planner/:path*', missing: [{ type: 'header', key: 'next-router-prefetch' }, { type: 'header', key: 'purpose', value: 'prefetch' }] },
    { source: '/notetaker/:path*', missing: [{ type: 'header', key: 'next-router-prefetch' }, { type: 'header', key: 'purpose', value: 'prefetch' }] },
    { source: '/profile/:path*', missing: [{ type: 'header', key: 'next-router-prefetch' }, { type: 'header', key: 'purpose', value: 'prefetch' }] },
  ],
}
