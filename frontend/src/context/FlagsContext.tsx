"use client";
import React, { createContext, useContext, useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";

import { useUser } from "@/context/UserContext";
import { isAppShellRoute } from "@/lib/appRoutes";
import { fetchFlags, type FlagMap } from "@/lib/flags";
import { ACCOUNT_REFRESH_MS, setProductAnalyticsFlag } from "@/lib/analytics";

/** Every registered flag's variants[0] is "off" (backend REGISTRY). */
const OFF = "off";

/**
 * The last flags this browser read successfully for a student (#771). A
 * `hide_*` flag's "off" UN-hides its feature, so an outage must not fall back
 * to "off": a failed (or degraded) read keeps the last-known map instead.
 * Flags are not sensitive; keyed per user so a switch never inherits another
 * student's map.
 */
const STORE_PREFIX = "sapling.flags.v1:";

export function readLastKnownFlags(who: string): FlagMap | null {
  try {
    const raw = window.localStorage.getItem(STORE_PREFIX + who);
    const parsed: unknown = raw ? JSON.parse(raw) : null;
    return parsed && typeof parsed === "object" ? (parsed as FlagMap) : null;
  } catch {
    return null;
  }
}

function rememberFlags(who: string, flags: FlagMap): void {
  try {
    window.localStorage.setItem(STORE_PREFIX + who, JSON.stringify(flags));
  } catch {
    // Storage full or blocked: the in-memory map still works this session.
  }
}

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
      let fresh = false;
      if (who) {
        try {
          f = await fetchFlags();
          fresh = true;
        } catch {
          // #771: unreadable flags keep this student's last-known map (a
          // hidden feature stays hidden); with none, every variant's "off".
          f = readLastKnownFlags(who) ?? {};
        }
      }
      if (gen !== generation.current) return;
      if (who && fresh) rememberFlags(who, f);
      setFlags(who ? f : null);
      setLoadedFor(who);
      loadedAt.current = Date.now();
      // #677/#675: product_analytics gates posthog-js, fail-closed: only a
      // FRESH read can turn it on, never a remembered one.
      setProductAnalyticsFlag(who !== null && fresh && f.product_analytics === "on");
    })();
  }, [userReady, isAuthenticated, userId, onAppRoute, loadedFor]);

  // #675 re-review / #771: re-read the flags every ACCOUNT_REFRESH_MS
  // (visible tabs only) and on coming back to the tab, so an admin switching
  // `product_analytics` off — or hiding/unhiding a nav feature — reaches tabs
  // that are already open. Independent of product_analytics: the nav flags
  // need it just as much. Updated in place — no clearing, so nav gating never
  // flickers. A failed refresh turns analytics off (fail closed) and keeps
  // the rest.
  useEffect(() => {
    const who = isAuthenticated && userId ? userId : null;
    if (!who || loadedFor !== who || !onAppRoute) return;
    const tick = () => {
      if (document.visibilityState !== "visible") return;
      if (Date.now() - loadedAt.current < ACCOUNT_REFRESH_MS) return;
      const gen = generation.current; // a user switch bumps it: then ignore
      loadedAt.current = Date.now();
      void fetchFlags().then(
        (f) => {
          if (gen !== generation.current) return;
          rememberFlags(who, f);
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
  }, [isAuthenticated, userId, loadedFor, onAppRoute]);

  // Ready = this user's answer is in (an error counts: it reads the
  // last-known map, else all-off).
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
