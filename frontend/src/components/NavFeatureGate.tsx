"use client";
import React, { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";

import { useFlagMap } from "@/context/FlagsContext";
import { navFlagForPath } from "@/lib/navFeatures";

/**
 * Sends a hidden feature's routes to /dashboard (#620). While flags load, a
 * flagged route's page stays mounted (its data fetches start as usual) but
 * invisible, so a hidden feature never flashes before the redirect.
 *
 * Always one `display: contents` wrapper, whatever the route or state, so
 * toggling visibility never remounts the page and adds no layout box.
 */
export function NavFeatureGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { flags, ready } = useFlagMap();
  const flag = navFlagForPath(pathname);
  const hidden = flag !== null && ready && flags[flag] === "on";
  const veiled = flag !== null && (!ready || hidden);

  useEffect(() => {
    if (hidden) router.replace("/dashboard");
  }, [hidden, router]);

  return (
    <div
      data-testid="nav-feature-gate"
      data-veiled={veiled || undefined}
      aria-hidden={veiled || undefined}
      style={{ display: "contents", visibility: veiled ? "hidden" : undefined }}
    >
      {children}
    </div>
  );
}
