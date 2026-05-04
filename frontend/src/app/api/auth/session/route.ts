import { NextRequest, NextResponse } from 'next/server';
import { signSession, SESSION_MAX_AGE } from '@/lib/sessionToken';

const SESSION_SECRET = process.env.SESSION_SECRET;

async function verifyAuthToken(token: string): Promise<string | null> {
  if (!SESSION_SECRET) return null;
  const dot = token.lastIndexOf('.');
  if (dot < 0) return null;
  const payloadB64 = token.slice(0, dot);
  const sigB64 = token.slice(dot + 1);
  try {
    function b64urlToBytes(s: string): Uint8Array<ArrayBuffer> {
      const padded = s.replace(/-/g, '+').replace(/_/g, '/');
      const pad = '='.repeat((4 - (padded.length % 4)) % 4);
      const binary = atob(padded + pad);
      const buf = new ArrayBuffer(binary.length);
      const bytes = new Uint8Array(buf);
      for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
      return bytes;
    }

    const key = await crypto.subtle.importKey(
      'raw',
      new TextEncoder().encode(SESSION_SECRET),
      { name: 'HMAC', hash: 'SHA-256' },
      false,
      ['verify'],
    );
    const valid = await crypto.subtle.verify(
      'HMAC',
      key,
      b64urlToBytes(sigB64),
      new TextEncoder().encode(payloadB64),
    );
    if (!valid) return null;

    const payload = JSON.parse(new TextDecoder().decode(b64urlToBytes(payloadB64)));
    if (typeof payload.exp !== 'number' || payload.exp < Math.floor(Date.now() / 1000)) return null;
    if (typeof payload.user_id !== 'string') return null;
    return payload.user_id;
  } catch {
    return null;
  }
}

export async function POST(request: NextRequest) {
  const body = await request.json();
  const { authToken } = body as { authToken?: string };

  if (!SESSION_SECRET) {
    return NextResponse.json(
      { error: 'SESSION_SECRET is not configured on the frontend deployment' },
      { status: 500 },
    );
  }
  if (!authToken) {
    return NextResponse.json({ error: 'authToken is required' }, { status: 400 });
  }

  const verifiedUserId = await verifyAuthToken(authToken);
  if (!verifiedUserId) {
    return NextResponse.json(
      { error: 'Invalid or expired auth token (SESSION_SECRET likely does not match the backend)' },
      { status: 401 },
    );
  }

  try {
    const token = await signSession(verifiedUserId);
    const response = NextResponse.json({ ok: true });
    response.cookies.set('sapling_session', token, {
      httpOnly: true,
      sameSite: 'none',
      secure: true,
      path: '/',
      maxAge: SESSION_MAX_AGE,
    });
    return response;
  } catch {
    return NextResponse.json({ error: 'Session signing failed — SESSION_SECRET may not be configured' }, { status: 500 });
  }
}

export async function DELETE() {
  const response = NextResponse.json({ ok: true });
  response.cookies.set('sapling_session', '', {
    httpOnly: true,
    sameSite: 'none',
    secure: true,
    path: '/',
    maxAge: 0,
  });
  return response;
}
