'use client';

import { useCallback, useEffect, useState } from 'react';

/** Error codes are short snake_case identifiers (SignInModal's ERROR_COPY keys). */
const ERROR_CODE_RE = /^[a-z_]{1,40}$/;

/**
 * A failed sign-in lands on `/?error=<code>` — the backend's same-tab OAuth
 * failure redirect, the callback page's `fail()`, the middleware and
 * UserContext's dead-session bounce. Before #756 nothing on the landing read
 * it, so the student saw no reason at all (an `account_deleted` refusal
 * looked like nothing happened).
 *
 * Reads the code once on mount, then strips it from the address bar so a
 * reload or a shared link doesn't replay it. Returns the code (null when
 * absent or malformed) and a clear function for when the modal closes.
 */
export function useSignInErrorParam(): [string | null, () => void] {
  const [code, setCode] = useState<string | null>(null);

  useEffect(() => {
    const url = new URL(window.location.href);
    const raw = url.searchParams.get('error');
    if (raw === null) return;
    url.searchParams.delete('error');
    window.history.replaceState(window.history.state, '', `${url.pathname}${url.search}${url.hash}`);
    // The URL is only readable after mount (the page is server-rendered), so
    // this one-shot read has to set state from the effect.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (ERROR_CODE_RE.test(raw)) setCode(raw);
  }, []);

  const clear = useCallback(() => setCode(null), []);
  return [code, clear];
}
