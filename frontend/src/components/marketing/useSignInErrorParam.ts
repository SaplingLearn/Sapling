'use client';

import { useCallback, useEffect, useState } from 'react';

/** Error codes are short snake_case identifiers (signInErrors.ts keys). */
const ERROR_CODE_RE = /^[a-z_]{1,40}$/;

/** Reads `name` off the address bar and strips it, so a reload or a shared
 * link doesn't replay it. Null when absent. Browser only. */
function takeParam(name: string): string | null {
  const url = new URL(window.location.href);
  const raw = url.searchParams.get(name);
  if (raw === null) return null;
  url.searchParams.delete(name);
  window.history.replaceState(window.history.state, '', `${url.pathname}${url.search}${url.hash}`);
  return raw;
}

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
    const raw = takeParam('error');
    // The URL is only readable after mount (the page is server-rendered), so
    // this one-shot read has to set state from the effect.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (raw !== null && ERROR_CODE_RE.test(raw)) setCode(raw);
  }, []);

  const clear = useCallback(() => setCode(null), []);
  return [code, clear];
}

/**
 * `/?signin=1` asks the landing to open the sign-in box: the companion pages'
 * Sign In link, and onboarding when it finds no one signed in. Read once on
 * mount and stripped like `?error=`. Returns whether it was asked for, and a
 * clear function for when the box closes.
 */
export function useSignInRequestParam(): [boolean, () => void] {
  const [asked, setAsked] = useState(false);

  useEffect(() => {
    // Read after mount, for the same reason as useSignInErrorParam's.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (takeParam('signin') !== null) setAsked(true);
  }, []);

  const clear = useCallback(() => setAsked(false), []);
  return [asked, clear];
}
