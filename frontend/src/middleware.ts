import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'
import { verifySession } from '@/lib/sessionToken'

const PROTECTED = [
  '/dashboard', '/learn', '/study', '/tree',
  '/flashcards', '/library', '/calendar', '/social'
]

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
  if (!session.approved) {
    return NextResponse.redirect(new URL('/pending', request.url))
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
