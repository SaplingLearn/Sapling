import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'
import { verifySession } from '@/lib/sessionToken'

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
const API_URL =
  (process.env.BACKEND_URL ?? '').trim() ||
  (process.env.NEXT_PUBLIC_API_URL ?? '').trim()

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

export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl

  const isProtected = PROTECTED.some(p => pathname.startsWith(p))
  if (!isProtected) return NextResponse.next()

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

export const config = {
  matcher: [
    '/dashboard/:path*', '/learn/:path*', '/quiz/:path*', '/study/:path*',
    '/tree/:path*', '/library/:path*',
    '/calendar/:path*', '/social/:path*',
    '/settings/:path*', '/achievements/:path*',
    '/admin/:path*',
    '/gradebook/:path*', '/course-planner/:path*', '/notetaker/:path*',
    '/profile/:path*'
  ]
}
