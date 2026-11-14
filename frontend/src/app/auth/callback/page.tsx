'use client';

import { Suspense, useEffect } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import { useUser } from '@/context/UserContext';
import { API_URL } from '@/lib/api';
import { postSignInRoute } from '@/lib/localSeed';
import { stashPendingToken } from '@/lib/pendingToken';
import { signInErrorMessage } from '@/components/marketing/signInErrors';

interface MeBody {
  onboarding_completed?: boolean;
  name?: string;
  avatar_url?: string;
}

/** Error codes are short snake_case identifiers (signInErrors.ts keys). */
const ERROR_CODE_RE = /^[a-z_]{1,40}$/;

/** What the page says while it hands a failed sign-in on: the reason, not
 * "Signing you in…" (a popup whose window can't close stays on it). An
 * unapproved sign-in is not a failure here: it goes on to /pending. */
function statusText(error: string | null): string {
  if (!error || error === 'not_approved') return 'Signing you in…';
  return ERROR_CODE_RE.test(error) ? signInErrorMessage(error) : signInErrorMessage('signin_failed');
}

/** Backoff between GET /api/auth/me attempts; one more attempt than delays. */
const ME_RETRY_DELAYS_MS = [300, 1000];

/** GET /api/auth/me with retries (#757). Network errors, 5xx and 429 are
 * retried; any other non-OK answer (401/403/404: no live account) is final.
 * Null when the profile could not be read. */
async function fetchMe(): Promise<MeBody | null> {
  for (let attempt = 0; ; attempt++) {
    try {
      const r = await fetch(`${API_URL}/api/auth/me`, { credentials: 'include' });
      if (r.ok) return (await r.json()) as MeBody;
      if (r.status < 500 && r.status !== 429) return null;
    } catch {}
    if (attempt >= ME_RETRY_DELAYS_MS.length) return null;
    await new Promise((resolve) => setTimeout(resolve, ME_RETRY_DELAYS_MS[attempt]));
  }
}

function CallbackInner() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const { setActiveUser } = useUser();

  useEffect(() => {
    const userId = searchParams.get('user_id');
    const avatarParam = searchParams.get('avatar');
    const approvedParam = searchParams.get('is_approved');
    const authToken = searchParams.get('auth_token');
    const error = searchParams.get('error');
    const popupId = searchParams.get('popup_id');

    // Popup mode is signalled by the backend echoing back popup_id we sent
    // when opening the window. We can't trust window.opener here: COOP nulls
    // it the moment the popup hops to a cross-origin URL (Railway/Google).
    const isPopup = !!popupId && typeof window !== 'undefined';

    const broadcast = (payload: Record<string, unknown>): boolean => {
      if (!isPopup || typeof BroadcastChannel === 'undefined') return false;
      try {
        const ch = new BroadcastChannel(`sapling_signin:${popupId}`);
        ch.postMessage({ type: 'sapling_signin', ...payload });
        ch.close();
      } catch {}
      try { window.close(); } catch {}
      return true;
    };

    // A cancelled Google sign-in arrives here as error=cancelled (popup mode;
    // a same-tab one goes straight to /?error=cancelled), like any failure:
    // the opener's sign-in box, or the landing's, says "Sign-in was cancelled."
    const fail = (errCode: string) => {
      if (broadcast({ success: false, error: errCode })) return;
      router.replace(`/?error=${encodeURIComponent(errCode)}`);
    };

    if (error === 'not_approved' || approvedParam === 'false') {
      // The backend hands an unapproved sign-in a short-lived pending token
      // (not a session) so /pending can show where they stand and let them
      // join the waitlist. Popup mode passes it to the opener — the popup's
      // sessionStorage dies with it; same-tab stashes it and goes there.
      const pendingToken = searchParams.get('pending_token');
      if (pendingToken) {
        if (broadcast({ success: false, error: 'not_approved', pendingToken })) return;
        stashPendingToken(pendingToken);
        router.replace('/pending');
        return;
      }
      fail('not_approved');
      return;
    }
    if (approvedParam !== 'true' || !userId) {
      fail(error || 'signin_failed');
      return;
    }

    (async () => {
      try {
        const sessionRes = await fetch('/api/auth/session', {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ userId, ...(authToken ? { authToken } : {}) }),
        });
        if (!sessionRes.ok) {
          fail('signin_failed');
          return;
        }
      } catch {
        fail('signin_failed');
        return;
      }

      // #191 + #757: GET /api/auth/me decides where this sign-in lands (its
      // `onboarding_completed`) and is what makes the identity durable, so
      // it is never guessed. A transient failure is retried; if it still
      // can't be read, the sign-in fails visibly — it used to default to
      // "onboarded" and silently skip onboarding for a new account. The
      // half-made session is dropped so a retry starts clean.
      const me = await fetchMe();
      if (!me) {
        try {
          await fetch('/api/auth/session', { method: 'DELETE', credentials: 'include' });
        } catch {}
        fail('signin_failed');
        return;
      }
      const onboardingCompleted = !!me.onboarding_completed;
      const name = me.name || '';
      const avatar = me.avatar_url || avatarParam || '';

      if (!isPopup) {
        setActiveUser(userId, name, avatar, { persist: true });
      }

      if (broadcast({
        success: true,
        userId,
        name,
        avatar,
        onboardingCompleted,
        profileConfirmed: true,
      })) return;

      // #715: a new account on a local backend waits for its sample data;
      // anywhere else this is /onboarding, as before. (Popup mode returned
      // above: the opener's SignInModal makes the same call.)
      router.replace(await postSignInRoute(onboardingCompleted));
    })();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div
      role="status"
      data-testid="auth-callback-status"
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'var(--bg)',
        color: 'var(--text-dim)',
        fontSize: 14,
      }}
    >
      {statusText(searchParams.get('error'))}
    </div>
  );
}

export default function CallbackPage() {
  return (
    <Suspense fallback={<div style={{ minHeight: '100vh', background: 'var(--bg)' }} />}>
      <CallbackInner />
    </Suspense>
  );
}
