import { NextRequest, NextResponse } from 'next/server';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? '';
const SESSION_MAX_AGE = 2592000; // 30 days

export async function POST(request: NextRequest) {
  const { userId } = await request.json();
  if (!userId || typeof userId !== 'string') {
    return NextResponse.json({ error: 'Missing userId' }, { status: 400 });
  }

  // Verify with the backend that the user exists and is approved.
  let approved = false;
  try {
    const res = await fetch(`${API_URL}/auth/me?user_id=${encodeURIComponent(userId)}`);
    if (!res.ok) {
      return NextResponse.json({ error: 'User not found' }, { status: 401 });
    }
    const data = await res.json();
    approved = data.is_approved === true;
  } catch {
    return NextResponse.json({ error: 'Backend unreachable' }, { status: 502 });
  }

  if (!approved) {
    return NextResponse.json({ error: 'Not approved' }, { status: 403 });
  }

  const response = NextResponse.json({ ok: true });
  response.cookies.set('sapling_session', userId, {
    httpOnly: true,
    sameSite: 'lax',
    path: '/',
    maxAge: SESSION_MAX_AGE,
  });
  response.cookies.set('sapling_approved', '1', {
    httpOnly: true,
    sameSite: 'lax',
    path: '/',
    maxAge: SESSION_MAX_AGE,
  });
  return response;
}

export async function DELETE() {
  const response = NextResponse.json({ ok: true });
  response.cookies.set('sapling_session', '', { httpOnly: true, maxAge: 0, path: '/' });
  response.cookies.set('sapling_approved', '', { httpOnly: true, maxAge: 0, path: '/' });
  return response;
}
