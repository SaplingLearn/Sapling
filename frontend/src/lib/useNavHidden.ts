"use client";
import { useCallback } from "react";

import { useFlagMap } from "@/context/FlagsContext";
import { navFlagForPath } from "@/lib/navFeatures";

/**
 * Whether a path leads to a feature this student's flags hide (#620): for a
 * link or a line of copy that points at ANOTHER destination, so it can go
 * somewhere visible instead of to a page NavFeatureGate would bounce to the
 * Dashboard.
 *
 * Only a loaded "on" hides, as in NavFeatureGate: while the flags load (and
 * off the app shell, where there are none) nothing reads as hidden, so the
 * usual link shows rather than flickering in afterwards.
 */
export function useIsNavHidden(): (path: string) => boolean {
  const { flags, ready } = useFlagMap();
  return useCallback(
    (path: string) => {
      const flag = navFlagForPath(path.split(/[?#]/)[0]);
      return flag !== null && ready && flags[flag] === "on";
    },
    [flags, ready],
  );
}
