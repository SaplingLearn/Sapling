import { NextRequest, NextResponse } from 'next/server';
import { signSession, SESSION_MAX_AGE } from '@/lib/sessionToken';

const API_URL = process.env.NEXT_PUBLIC_API_URL;
const SESSION_SECRET = process.env.SESSION_SECRET;

// Verify an HMAC token produced by the backend's OAuth callback.
// Returns the userId if valid and unexpired, otherwise null.
async function verifyAuthToken(token: string): Promise<string | null> {
  if (!SESSION_SECRET) return null;
  const dot = token.lastIndexOf('.');
  if (dot < 0) return null;
  const payloadB64 = token.slice(0, dot);
  const sigB64 = token.slice(dot + 1);
  try {
    // Re-pad base64url and convert to bytes for sig comparison.
    // Returns Uint8Array<ArrayBuffer> (concrete) so it satisfies BufferSource.
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
  const { userId, authToken } = body as { userId?: string; authToken?: string };

  let verifiedUserId: string | null = null;

  // Fast path: verify the backend-signed token (no round-trip needed).
  if (authToken) {
    verifiedUserId = await verifyAuthToken(authToken);
    if (!verifiedUserId) {
      return NextResponse.json({ error: 'Invalid or expired auth token' }, { status: 401 });
    }
  } else {
    // Fallback: call backend to verify (used when SESSION_SECRET not shared yet).
    if (!API_URL) {
      return NextResponse.json({ error: 'NEXT_PUBLIC_API_URL not configured' }, { status: 500 });
    }
    if (!userId || typeof userId !== 'string') {
      return NextResponse.json({ error: 'Missing userId' }, { status: 400 });
    }
    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 3000);
      let res: Response;
      try {
        res = await fetch(`${API_URL}/api/auth/me?user_id=${encodeURIComponent(userId)}`, { signal: controller.signal });
      } finally {
        clearTimeout(timeout);
      }
      if (!res.ok) {
        return NextResponse.json({ error: 'User not found' }, { status: 401 });
      }
      const data = await res.json();
      if (data.is_approved !== true) {
        return NextResponse.json({ error: 'Not approved' }, { status: 403 });
      }
      verifiedUserId = userId;
    } catch {
      return NextResponse.json({ error: 'Backend unreachable' }, { status: 502 });
    }
  }

  try {
    const token = await signSession(verifiedUserId);
    const response = NextResponse.json({ ok: true });
    response.cookies.set('sapling_session', token, {
      httpOnly: true,
      sameSite: 'lax',
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
  response.cookies.set('sapling_session', '', { httpOnly: true, maxAge: 0, path: '/' });
  return response;
}
