import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'
import { verifySession } from '@/lib/sessionToken'

const PROTECTED = [
  '/dashboard', '/learn', '/study', '/tree',
  '/library', '/calendar', '/social',
  '/settings', '/achievements', '/admin'
]

const API_URL = process.env.NEXT_PUBLIC_API_URL

function googleAuthRedirect() {
  if (!API_URL) return null
  return new URL('/api/auth/google', API_URL).toString()
}

function redirectToGoogleOrSignin(request: NextRequest) {
  const g = googleAuthRedirect()
  if (g) return NextResponse.redirect(g)
  const u = new URL('/auth', request.url)
  u.searchParams.set('error', 'google_not_configured')
  return NextResponse.redirect(u)
}

export async function middleware(request: NextRequest) {
  if (process.env.NEXT_PUBLIC_LOCAL_MODE === 'true') {
    return NextResponse.next()
  }

  const { pathname } = request.nextUrl

  // Mirror pre-revamp behavior: an already-signed-in user hitting /auth or
  // /auth/callback should bounce straight to /dashboard instead of seeing
  // the sign-in form again. Pre-revamp handled this via a redirectIfSignedIn
  // helper on /signin; the route moved but the behavior shouldn't regress.
  if (pathname === '/auth' || pathname === '/auth/') {
    const token = request.cookies.get('sapling_session')?.value
    if (token && (await verifySession(token))) {
      return NextResponse.redirect(new URL('/dashboard', request.url))
    }
    return NextResponse.next()
  }

  const isProtected = PROTECTED.some(p => pathname.startsWith(p))
  if (!isProtected) return NextResponse.next()

  const token = request.cookies.get('sapling_session')?.value
  if (!token) return redirectToGoogleOrSignin(request)

  const session = await verifySession(token)
  if (!session) return redirectToGoogleOrSignin(request)

  if (!API_URL) return redirectToGoogleOrSignin(request)
  try {
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 3000)
    let res: Response
    try {
      res = await fetch(
        `${API_URL}/api/auth/me?user_id=${encodeURIComponent(session.userId)}`,
        { signal: controller.signal },
      )
    } finally {
      clearTimeout(timeout)
    }
    if (!res.ok) return redirectToGoogleOrSignin(request)
    const data = await res.json()
    if (data.is_approved !== true) return NextResponse.redirect(new URL('/pending', request.url))
  } catch {
    return redirectToGoogleOrSignin(request)
  }

  return NextResponse.next()
}

export const config = {
  matcher: [
    '/auth', '/auth/',  // for the signed-in -> /dashboard redirect
    '/dashboard/:path*', '/learn/:path*', '/study/:path*',
    '/tree/:path*', '/library/:path*',
    '/calendar/:path*', '/social/:path*',
    '/settings/:path*', '/achievements/:path*',
    '/admin/:path*'
  ]
}
