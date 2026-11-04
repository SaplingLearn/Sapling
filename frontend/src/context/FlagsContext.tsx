"use client";
import React, { createContext, useContext, useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";

import { useUser } from "@/context/UserContext";
import { isAppShellRoute } from "@/lib/appRoutes";
import { fetchFlags, type FlagMap } from "@/lib/flags";
import { ACCOUNT_REFRESH_MS, setProductAnalyticsFlag } from "@/lib/analytics";

/** Every registered flag's variants[0] is "off" (backend REGISTRY). */
const OFF = "off";

const FlagsContext = createContext<{ flags: FlagMap | null; onAppRoute: boolean; ready: boolean }>({
  flags: null,
  onAppRoute: false,
  ready: true,
});

export function FlagsProvider({ children }: { children: React.ReactNode }) {
  const { userId, isAuthenticated, userReady } = useUser();
  const onAppRoute = isAppShellRoute(usePathname());
  const [flags, setFlags] = useState<FlagMap | null>(null);
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const generation = useRef(0);
  const loadedAt = useRef(0);

  useEffect(() => {
    if (!userReady) return;
    const who = isAuthenticated && userId ? userId : null;
    if (who && (!onAppRoute || loadedFor === who)) return;
    const gen = ++generation.current;
    // Signed out: clear the flags (and the analytics flag), no request —
    // analytics teardown itself (stopAnalytics) is the UserProvider's. Signed
    // in: fetch this student's flags. Both settle through the same staleness guard (`gen`),
    // so a response overtaken by a user switch or a sign-out is ignored.
    // Wrapped in an inner async function (never called directly from the
    // effect body) so every state setter runs from a callback, not
    // synchronously in the effect — react-hooks/set-state-in-effect.
    void (async () => {
      setFlags(null);
      // The previous user's analytics flag must not stay in force while this
      // user's flags are in flight: off until this refetch settles.
      setProductAnalyticsFlag(false);
      let f: FlagMap = {};
      if (who) {
        try {
          f = await fetchFlags();
        } catch {
          // Unreadable flags resolve to every variant's "off".
        }
      }
      if (gen !== generation.current) return;
      setFlags(who ? f : null);
      setLoadedFor(who);
      loadedAt.current = Date.now();
      // #677/#675: product_analytics gates posthog-js (fail-closed: an error
      // above leaves `f` empty, so it stays off).
      setProductAnalyticsFlag(who !== null && f.product_analytics === "on");
    })();
  }, [userReady, isAuthenticated, userId, onAppRoute, loadedFor]);

  // #675 re-review: while pageviews are flowing, re-read the flags every
  // ACCOUNT_REFRESH_MS (visible tabs only) and on coming back to the tab, so
  // an admin switching `product_analytics` off reaches tabs that are already
  // open. Updated in place — no clearing, so nav gating never flickers. A
  // failed refresh turns analytics off (fail closed) and keeps the rest.
  const analyticsOn = flags?.product_analytics === "on";
  useEffect(() => {
    const who = isAuthenticated && userId ? userId : null;
    if (!who || loadedFor !== who || !onAppRoute || !analyticsOn) return;
    const tick = () => {
      if (document.visibilityState !== "visible") return;
      if (Date.now() - loadedAt.current < ACCOUNT_REFRESH_MS) return;
      const gen = generation.current; // a user switch bumps it: then ignore
      loadedAt.current = Date.now();
      void fetchFlags().then(
        (f) => {
          if (gen !== generation.current) return;
          setFlags(f);
          setProductAnalyticsFlag(f.product_analytics === "on");
        },
        () => {
          if (gen === generation.current) setProductAnalyticsFlag(false);
        },
      );
    };
    const timer = window.setInterval(tick, ACCOUNT_REFRESH_MS);
    document.addEventListener("visibilitychange", tick);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", tick);
    };
  }, [isAuthenticated, userId, loadedFor, onAppRoute, analyticsOn]);

  // Ready = this user's answer is in (an error counts: it reads all-off).
  // Signed out there is nothing to wait for.
  const who = isAuthenticated && userId ? userId : null;
  const ready = userReady && (who === null || (loadedFor === who && flags !== null));

  return <FlagsContext.Provider value={{ flags, onAppRoute, ready }}>{children}</FlagsContext.Provider>;
}

/** The variant of `key` for this student; "off" until loaded, on error, off-shell. */
export function useFlag(key: string): string {
  const { flags, onAppRoute } = useContext(FlagsContext);
  if (!onAppRoute || !flags) return OFF;
  return flags[key] ?? OFF;
}

const NO_FLAGS: FlagMap = {};

/**
 * Every client-visible flag at once, plus whether they have loaded — for
 * callers that must not act on the "off" placeholder (NavFeatureGate would
 * otherwise show a hidden feature's page while flags are in flight). Off the
 * app shell (and outside a provider) there is nothing to load: ready, empty.
 */
export function useFlagMap(): { flags: FlagMap; ready: boolean } {
  const { flags, onAppRoute, ready } = useContext(FlagsContext);
  if (!onAppRoute) return { flags: NO_FLAGS, ready: true };
  return { flags: flags ?? NO_FLAGS, ready };
}
