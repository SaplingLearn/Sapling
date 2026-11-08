"use client";
import React from "react";

/**
 * "Latest request wins" for async UI work (#769).
 *
 * Every screen that fires a request from an effect or a handler and then
 * writes the reply into state has the same race: an OLDER request resolving
 * after a newer one overwrites the newer result (or its `finally` clears a
 * loading flag the newer request still owns). This hook is the one shared
 * fix — a monotonically increasing run counter:
 *
 *   const latest = useLatestRequest();
 *   const run = latest.begin();          // supersedes every earlier token
 *   const r = await fetchSomething();
 *   if (!run.isCurrent()) return;        // a newer run (or unmount) owns state now
 *   setState(r);
 *
 * `cancel()` invalidates every outstanding token without starting a new one —
 * an effect returns it as its cleanup so a dependency change or unmount drops
 * the in-flight reply. Unmount cancels automatically.
 *
 * Tokens, not AbortController: the reply is ignored, the request is not torn
 * down. That is all these call sites need (none of their requests is
 * expensive to finish) and it works for every api.ts helper without
 * threading a signal through each one.
 *
 * Independent races need independent hooks: one `useLatestRequest()` per
 * logical slot (exam list vs guide), or a begin() on one would cancel the
 * other.
 */
export interface RequestToken {
  /** True while no later begin()/cancel() (or unmount) has happened. */
  isCurrent: () => boolean;
}

export interface LatestRequest {
  begin: () => RequestToken;
  cancel: () => void;
}

export function useLatestRequest(): LatestRequest {
  const seq = React.useRef(0);
  const api = React.useMemo<LatestRequest>(
    () => ({
      begin: () => {
        const id = ++seq.current;
        return { isCurrent: () => seq.current === id };
      },
      cancel: () => {
        seq.current++;
      },
    }),
    [],
  );
  React.useEffect(() => api.cancel, [api]);
  return api;
}
