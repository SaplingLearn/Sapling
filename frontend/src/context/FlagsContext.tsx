"use client";
import React, { createContext, useContext, useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";

import { useUser } from "@/context/UserContext";
import { isAppShellRoute } from "@/lib/appRoutes";
import { fetchFlags, type FlagMap } from "@/lib/flags";
import { setProductAnalyticsFlag } from "@/lib/analytics";

/** Every registered flag's variants[0] is "off" (backend REGISTRY). */
const OFF = "off";

const FlagsContext = createContext<{ flags: FlagMap | null; onAppRoute: boolean }>({
  flags: null,
  onAppRoute: false,
});

export function FlagsProvider({ children }: { children: React.ReactNode }) {
  const { userId, isAuthenticated, userReady } = useUser();
  const onAppRoute = isAppShellRoute(usePathname());
  const [flags, setFlags] = useState<FlagMap | null>(null);
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const generation = useRef(0);

  useEffect(() => {
    if (!userReady) return;
    const who = isAuthenticated && userId ? userId : null;
    if (who && (!onAppRoute || loadedFor === who)) return;
    const gen = ++generation.current;
    // Signed out: clear and stop analytics, no request. Signed in: fetch this
    // student's flags. Both settle through the same staleness guard (`gen`),
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
      let ok = true;
      if (who) {
        try {
          f = await fetchFlags();
        } catch {
          ok = false;
        }
      }
      if (gen !== generation.current) return;
      setFlags(who ? f : null);
      setLoadedFor(who);
      setProductAnalyticsFlag(who !== null && ok && f.product_analytics === "on");
    })();
  }, [userReady, isAuthenticated, userId, onAppRoute, loadedFor]);

  return <FlagsContext.Provider value={{ flags, onAppRoute }}>{children}</FlagsContext.Provider>;
}

/** The variant of `key` for this student; "off" until loaded, on error, off-shell. */
export function useFlag(key: string): string {
  const { flags, onAppRoute } = useContext(FlagsContext);
  if (!onAppRoute || !flags) return OFF;
  return flags[key] ?? OFF;
}
