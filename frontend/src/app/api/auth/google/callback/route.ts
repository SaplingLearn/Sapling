import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:5000';

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);

  const backendUrl = new URL(`${BACKEND_URL}/api/auth/google/callback`);
  searchParams.forEach((value, key) => backendUrl.searchParams.set(key, value));

  // Fetch without following redirects so we get the Location header
  const response = await fetch(backendUrl.toString(), { redirect: 'manual' });

  const location = response.headers.get('location');
  if (location) {
    return NextResponse.redirect(location);
  }

  return NextResponse.redirect(new URL('/?error=auth_failed', request.url));
}
