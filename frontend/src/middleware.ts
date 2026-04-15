import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'
import { verifySession } from '@/lib/sessionToken'

const PROTECTED = [
  '/dashboard', '/learn', '/study', '/tree',
  '/flashcards', '/library', '/calendar', '/social'
]

const API_URL = process.env.NEXT_PUBLIC_API_URL

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl
  const isProtected = PROTECTED.some(p => pathname.startsWith(p))
  if (!isProtected) return NextResponse.next()

  const token = request.cookies.get('sapling_session')?.value
  if (!token) {
    return NextResponse.redirect(new URL('/signin', request.url))
  }

  const session = await verifySession(token)
  if (!session) {
    return NextResponse.redirect(new URL('/signin', request.url))
  }

  // Re-check approval live so revocation takes effect immediately.
  if (!API_URL) {
    return NextResponse.redirect(new URL('/signin', request.url))
  }
  try {
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 3000)
    let res: Response
    try {
      res = await fetch(
        `${API_URL}/auth/me?user_id=${encodeURIComponent(session.userId)}`,
        { signal: controller.signal },
      )
    } finally {
      clearTimeout(timeout)
    }
    if (!res.ok) {
      return NextResponse.redirect(new URL('/signin', request.url))
    }
    const data = await res.json()
    if (data.is_approved !== true) {
      return NextResponse.redirect(new URL('/pending', request.url))
    }
  } catch {
    return NextResponse.redirect(new URL('/signin', request.url))
  }

  return NextResponse.next()
}

export const config = {
  matcher: [
    '/dashboard/:path*', '/learn/:path*', '/study/:path*',
    '/tree/:path*', '/flashcards/:path*', '/library/:path*',
    '/calendar/:path*', '/social/:path*'
  ]
}
