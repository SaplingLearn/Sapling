import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

const PROTECTED = [
  '/dashboard', '/learn', '/study', '/tree',
  '/flashcards', '/library', '/calendar', '/social'
]

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl
  const isProtected = PROTECTED.some(p => pathname.startsWith(p))
  if (!isProtected) return NextResponse.next()

  const session = request.cookies.get('sapling_session')?.value
  const approved = request.cookies.get('sapling_approved')?.value

  if (!session) {
    return NextResponse.redirect(new URL('/signin', request.url))
  }
  if (approved !== '1') {
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
