import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'
import { verifySession } from '@/lib/sessionToken'

const PROTECTED = [
  '/dashboard', '/learn', '/study', '/tree',
  '/library', '/calendar', '/social',
  '/settings', '/achievements', '/admin',
  '/gradebook', '/course-planner'
]

const API_URL = process.env.NEXT_PUBLIC_API_URL

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
  if (process.env.NEXT_PUBLIC_LOCAL_MODE === 'true') {
    return NextResponse.next()
  }

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
    '/dashboard/:path*', '/learn/:path*', '/study/:path*',
    '/tree/:path*', '/library/:path*',
    '/calendar/:path*', '/social/:path*',
    '/settings/:path*', '/achievements/:path*',
    '/admin/:path*',
    '/gradebook/:path*', '/course-planner/:path*'
  ]
}
