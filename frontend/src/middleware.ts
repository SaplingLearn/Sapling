import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'
import { verifySession } from '@/lib/sessionToken'

const PROTECTED = [
  '/dashboard', '/learn', '/study', '/tree',
  '/flashcards', '/library', '/calendar', '/social',
  '/profile', '/settings', '/achievements', '/admin'
]

const API_URL = process.env.NEXT_PUBLIC_API_URL

function googleAuthRedirect() {
  if (!API_URL) return null
  return new URL('/api/auth/google', API_URL).toString()
}

function redirectToGoogleOrSignin(request: NextRequest) {
  const g = googleAuthRedirect()
  if (g) return NextResponse.redirect(g)
  const u = new URL('/signin', request.url)
  u.searchParams.set('error', 'google_not_configured')
  return NextResponse.redirect(u)
}

async function redirectIfSignedIn(request: NextRequest): Promise<NextResponse | null> {
  const token = request.cookies.get('sapling_session')?.value
  if (!token) return null
  const session = await verifySession(token)
  if (!session) return null
  if (!API_URL) return null
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
    if (!res.ok) return null
    const data = await res.json()
    const dest = data.is_approved === true ? '/dashboard' : '/pending'
    return NextResponse.redirect(new URL(dest, request.url))
  } catch {
    return null
  }
}

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl

  if (pathname === '/signin' || pathname === '/signin/') {
    const redirect = await redirectIfSignedIn(request)
    if (redirect) return redirect
    const hasError = request.nextUrl.searchParams.get('error')
    if (hasError) {
      return NextResponse.next()
    }
    return redirectToGoogleOrSignin(request)
  }

  const isProtected = PROTECTED.some(p => pathname.startsWith(p))
  if (!isProtected) return NextResponse.next()

  const token = request.cookies.get('sapling_session')?.value
  if (!token) {
    return redirectToGoogleOrSignin(request)
  }

  const session = await verifySession(token)
  if (!session) {
    return redirectToGoogleOrSignin(request)
  }

  // Re-check approval live so revocation takes effect immediately.
  if (!API_URL) {
    return redirectToGoogleOrSignin(request)
  }
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
    if (!res.ok) {
      return redirectToGoogleOrSignin(request)
    }
    const data = await res.json()
    if (data.is_approved !== true) {
      return NextResponse.redirect(new URL('/pending', request.url))
    }
  } catch {
    return redirectToGoogleOrSignin(request)
  }

  return NextResponse.next()
}

export const config = {
  matcher: [
    '/signin',
    '/dashboard/:path*', '/learn/:path*', '/study/:path*',
    '/tree/:path*', '/flashcards/:path*', '/library/:path*',
    '/calendar/:path*', '/social/:path*',
    '/profile/:path*', '/settings/:path*', '/achievements/:path*',
    '/admin/:path*'
  ]
}
