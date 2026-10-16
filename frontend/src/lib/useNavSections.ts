"use client";
import { useMemo } from "react";

import { useFlagMap } from "@/context/FlagsContext";
import { visibleNavSections, type NavSection } from "@/lib/navFeatures";

/**
 * The nav sections this student may see (#620). Until their flags have
 * loaded, flagged destinations are held back, so a hidden feature never
 * flashes into the nav; a failed load reads all-off and shows everything.
 */
export function useVisibleNavSections(): NavSection[] {
  const { flags, ready } = useFlagMap();
  return useMemo(
    () => visibleNavSections((flag) => !ready || flags[flag] === "on"),
    [flags, ready],
  );
}
